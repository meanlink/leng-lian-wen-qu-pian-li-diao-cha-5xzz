"""赔付核销：同批累计实付不超核定损失；确认、付款、对账、撤销、退款全程留痕。

设计要点：
- 货批余额（paid_cents / held_cents）只通过带守卫条件的原子 UPDATE 变动，
  并发核销共用余额时超额占用会在 SQL 层失败，不依赖先查后改。
- 付款单号按单幂等（PAY-订单号-A尝试号）：同单重试复用原单，同号改金额被付款端拒收。
- 回执只推进 pending/sent 状态且序号必须更新，旧回执不改新状态。
- 每个持久化步骤独立提交：中断后未结付款/退款可由 settle_sweep 恢复。
"""
import time, logging
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from sqlalchemy import select, update, func
from src.models import CargoBatch, PayoutOrder, Payment, Refund, FundEvent, Job
from src.services import paygate
from src.services.audit import record

HOLDING = ('confirmed', 'paying', 'cancelling')  # 占用可赔余额的订单状态
RECEIPT_GRACE_SECONDS = 3   # 回执宽限期，过后由对账推进
REFUND_RETRY_SECONDS = 5    # 退款失败重试退避


def to_cents(value, label='金额'):
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HTTPException(422, f'{label}须为数值')
        return  # pragma: no cover
    if not d.is_finite() or d <= 0:
        raise HTTPException(422, f'{label}须大于 0')
    if d != d.quantize(Decimal('0.01')):
        raise HTTPException(422, f'{label}最多两位小数')
    cents = int(d * 100)
    if cents > 10 ** 15:
        raise HTTPException(422, f'{label}超出支持范围')
    return cents


def _event(db, batch_id, order_id, kind, direction, cents, note='', actor='system'):
    batch = db.get(CargoBatch, batch_id)
    db.expire(batch, ['held_cents', 'paid_cents'])  # 计数器经 SQL 守卫更新，重读取快照
    db.add(FundEvent(batch_id=batch_id, order_id=order_id, kind=kind, direction=direction,
                     amount_cents=cents, available_after_cents=batch.approved_loss_cents - batch.paid_cents - batch.held_cents,
                     note=note[:290], actor=actor, at=time.time()))


# ---- 货批余额：全部经守卫 UPDATE 变动，并发安全 ----
def _hold(db, batch_id, cents):
    """占用可赔余额；同批累计（在途+实付）不超核定损失，超额则占用失败。"""
    n = db.execute(update(CargoBatch).where(CargoBatch.id == batch_id,
                                            CargoBatch.held_cents + CargoBatch.paid_cents + cents <= CargoBatch.approved_loss_cents)
                   .values(held_cents=CargoBatch.held_cents + cents)).rowcount
    return n == 1


def _release_hold(db, batch_id, cents):
    db.execute(update(CargoBatch).where(CargoBatch.id == batch_id).values(held_cents=CargoBatch.held_cents - cents))


def _mark_paid(db, batch_id, cents):
    """占用转为实付。"""
    db.execute(update(CargoBatch).where(CargoBatch.id == batch_id)
               .values(held_cents=CargoBatch.held_cents - cents, paid_cents=CargoBatch.paid_cents + cents))


def _mark_refunded(db, batch_id, cents):
    """退款确认后才释放可赔金额。"""
    db.execute(update(CargoBatch).where(CargoBatch.id == batch_id).values(paid_cents=CargoBatch.paid_cents - cents))


def latest_payment(db, order_id):
    return db.scalar(select(Payment).where(Payment.order_id == order_id).order_by(Payment.id.desc()).limit(1))


def latest_refund(db, order_id):
    return db.scalar(select(Refund).where(Refund.order_id == order_id).order_by(Refund.id.desc()).limit(1))


# ---- 开单 ----
def create_batch(db, data, user):
    code = data.code.strip().upper()
    if db.scalar(select(CargoBatch).where(CargoBatch.code == code)):
        raise HTTPException(409, '货批号已存在')
    b = CargoBatch(code=code, title=data.title.strip(), approved_loss_cents=to_cents(data.approved_loss, '核定损失'),
                   paid_cents=0, held_cents=0, created_at=time.time())
    db.add(b)
    db.flush()
    _event(db, b.id, None, 'batch.register', 'info', b.approved_loss_cents, '登记货批与核定损失', user.email)
    return b


def create_order(db, data, user):
    batch = db.get(CargoBatch, data.batch_id)
    if not batch:
        raise HTTPException(404, '货批不存在')
    cents = to_cents(data.claim_amount, '申报金额')
    if cents > batch.approved_loss_cents:
        raise HTTPException(422, '申报金额不能超过核定损失')
    ids = list(dict.fromkeys(data.investigation_ids or []))
    if not ids:
        raise HTTPException(422, '至少选择一份获批调查作为赔付依据')
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_(ids)))}
    missing = [i for i in ids if i not in jobs]
    if missing:
        raise HTTPException(404, f'调查不存在：{missing}')
    unapproved = [i for i in ids if not jobs[i].approved]
    if unapproved:
        raise HTTPException(409, f'调查未获批准，不能作为赔付依据：{unapproved}')
    o = PayoutOrder(order_no='', batch_id=batch.id, claim_cents=cents, investigation_ids=ids,
                    note=(data.note or '')[:300], status='draft', created_by=user.id, created_at=time.time())
    db.add(o)
    db.flush()
    o.order_no = (data.order_no or f'PO-{time.strftime("%Y%m%d")}-{o.id:04d}').strip()
    db.flush()
    _event(db, o.batch_id, o.id, 'order.created', 'info', cents, '开具赔付核销单（待财务确认）', user.email)
    return o


# ---- 确认与付款 ----
def confirm(db, order, actor):
    n = db.execute(update(PayoutOrder).where(PayoutOrder.id == order.id, PayoutOrder.status == 'draft')
                   .values(status='confirmed', confirmed_at=time.time())).rowcount
    if n != 1:
        raise HTTPException(409, '单据已确认或已撤销，请刷新')
    if not _hold(db, order.batch_id, order.claim_cents):
        raise HTTPException(409, '可赔余额不足：同批累计实付与在途占用将达核定损失上限')
    payment = Payment(payment_no=f'PAY-{order.order_no}-A1', order_id=order.id, batch_id=order.batch_id,
                      amount_cents=order.claim_cents, attempt=1, status='pending', created_at=time.time())
    db.add(payment)
    db.flush()
    _event(db, order.batch_id, order.id, 'hold', 'hold', order.claim_cents, '财务确认，占用可赔余额', actor)
    record(db, actor, 'payout.confirm', {'order_no': order.order_no, 'amount_cents': order.claim_cents})
    db.commit()
    dispatch_payment(db, payment.id, actor)
    db.refresh(order)
    return order


def dispatch_payment(db, payment_id, actor='system'):
    """发送付款并尝试领取回执。回执丢失不盲目再付，留待对账。"""
    p = db.get(Payment, payment_id)
    if not p or p.status != 'pending':
        return p
    order = db.get(PayoutOrder, p.order_id)
    db.refresh(order)  # 与撤销互斥：状态判断基于最新值（MySQL 下可配 with_for_update 串行化）
    if order.status not in ('confirmed', 'paying'):
        return p
    n = db.execute(update(Payment).where(Payment.id == p.id, Payment.status == 'pending')
                   .values(status='sent', sent_at=time.time(), note='')).rowcount
    if n != 1:
        db.rollback()
        return db.get(Payment, payment_id)  # 已被撤销或状态变化，不再发出
    db.commit()  # 发出状态先落库，再调付款端（付款端独立提交）
    try:
        paygate.submit_payment(p.payment_no, p.amount_cents, memo=order.order_no)  # 受理回执≠付款回执
    except paygate.Rejected as e:
        p.status = 'failed'
        p.note = str(e)[:290]
        p.settled_at = time.time()
        _fail_order(db, order, p, actor, str(e))
        db.commit()
        return p
    except paygate.GatewayError as e:
        db.execute(update(Payment).where(Payment.id == p.id, Payment.status == 'sent')
                   .values(status='pending', sent_at=None, note=str(e)[:290]))
        db.commit()
        return p  # 付款端不可用：回到待发送，单号幂等，重发安全
    db.refresh(p)
    if p.status == 'cancelled':
        # 提交途中被撤销但付款端已入账：立即等额退款冲正，不留孤儿付款
        try:
            paygate.submit_refund('REF-' + p.payment_no, p.payment_no, p.amount_cents)
            p.note = '付款与撤销竞速到达付款端，已自动等额退款冲正'
        except paygate.GatewayError:
            p.note = '付款与撤销竞速到达付款端，自动冲正失败，待人工对账'
        db.commit()
        return p
    db.execute(update(PayoutOrder).where(PayoutOrder.id == order.id, PayoutOrder.status == 'confirmed').values(status='paying'))
    _event(db, p.batch_id, p.order_id, 'pay.dispatch', 'info', p.amount_cents, f'付款 {p.payment_no} 已发出，待回执', actor)
    db.commit()
    try:
        receipt = paygate.fetch_receipt(p.payment_no)
    except paygate.ReceiptLost:
        _event(db, p.batch_id, p.order_id, 'pay.receipt_lost', 'info', p.amount_cents, '付款回执丢失，待对账（不盲目再付）', actor)
        db.commit()
        return p
    except paygate.GatewayError:
        return p
    if receipt:
        apply_payment_record(db, p.id, receipt, actor, source='回执')
    return db.get(Payment, payment_id)


def apply_payment_record(db, payment_id, rec, actor='system', source='对账'):
    """应用付款端记录（回执或对账结果）。旧回执不改新状态。"""
    p = db.get(Payment, payment_id)
    if not p:
        return None
    if p.status not in ('pending', 'sent'):
        record(db, actor, 'payout.payment.stale', {'payment_no': p.payment_no, 'status': p.status, 'source': source})
        db.commit()
        return p
    seq = rec.get('receipt_seq') or 0
    if p.receipt_seq and seq and seq <= p.receipt_seq:
        return p  # 更旧的回执，忽略
    if rec.get('amount_cents') != p.amount_cents:
        p.note = '对账金额不一致，待人工核对'
        _event(db, p.batch_id, p.order_id, 'pay.mismatch', 'info', p.amount_cents, '对账金额不一致，暂停推进', actor)
        db.commit()
        return p
    order = db.get(PayoutOrder, p.order_id)
    p.receipt_seq = seq or p.receipt_seq
    p.receipt = rec
    if rec['status'] == 'succeeded':
        p.status = 'succeeded'
        p.settled_at = time.time()
        _mark_paid(db, p.batch_id, p.amount_cents)
        _event(db, p.batch_id, p.order_id, 'pay.out', 'out', p.amount_cents, f'付款成功（经{source}确认），资金划出', actor)
        if order.status in ('confirmed', 'paying'):
            order.status = 'paid'
        elif order.status == 'cancelling':
            _start_refund(db, order, p, actor)  # 撤销遇在途付款：付款已成则退款冲回
    else:
        p.status = 'failed'
        p.settled_at = time.time()
        _fail_order(db, order, p, actor, '付款端退回')
    db.commit()
    db.refresh(order)
    if order.status == 'refunding':
        r = latest_refund(db, order.id)
        if r and r.status == 'pending':
            dispatch_refund(db, r.id, actor)
    return p


def _fail_order(db, order, payment, actor, reason):
    _release_hold(db, payment.batch_id, payment.amount_cents)
    _event(db, payment.batch_id, order.id, 'pay.failed', 'release', payment.amount_cents, f'付款失败（{reason[:200]}），释放占用', actor)
    if order.status in ('confirmed', 'paying'):
        order.status = 'failed'
        order.closed_at = time.time()
    elif order.status == 'cancelling':
        order.status = 'cancelled'
        order.closed_at = time.time()
        _event(db, payment.batch_id, order.id, 'order.cancelled', 'info', 0, '付款未成，核销单撤销', actor)


def reconcile_payment(db, payment_id, actor='system'):
    """对账：查付款端台账推进付款状态；付款端无记录则回到待发送（单号幂等，重发安全）。"""
    p = db.get(Payment, payment_id)
    if not p or p.status not in ('pending', 'sent'):
        return p
    rec = paygate.fetch_payment(p.payment_no)
    if not rec:
        if p.status == 'sent':
            db.execute(update(Payment).where(Payment.id == p.id, Payment.status == 'sent')
                       .values(status='pending', sent_at=None))
            _event(db, p.batch_id, p.order_id, 'pay.reconcile', 'info', p.amount_cents, '对账：付款端无记录，待重新发起', actor)
            db.commit()
            advance_order(db, db.get(PayoutOrder, p.order_id), actor)
        return db.get(Payment, payment_id)
    apply_payment_record(db, p.id, rec, actor, source='对账')
    return db.get(Payment, payment_id)


# ---- 撤销与退款 ----
def cancel(db, order, actor):
    st = order.status
    if st in ('cancelled', 'failed'):
        raise HTTPException(409, '核销单已关闭')
    if st in ('cancelling', 'refunding'):
        return order  # 撤销已在进行，幂等返回
    if st == 'draft':
        order.status = 'cancelled'
        order.closed_at = time.time()
        _event(db, order.batch_id, order.id, 'order.cancelled', 'info', 0, '未确认单据撤销', actor)
        db.commit()
        return order
    p = latest_payment(db, order.id)
    if p and (p.status == 'succeeded' or st == 'paid'):
        refund = _start_refund(db, order, p, actor)  # 已付通过退款冲回
        db.commit()
        dispatch_refund(db, refund.id, actor)
        db.refresh(order)
        return order
    if p and p.status == 'sent':
        order.status = 'cancelling'  # 付款在途：等对账，不盲目再付也不直接释放
        _event(db, order.batch_id, order.id, 'cancel.requested', 'info', p.amount_cents, '付款在途，撤销等待对账结果', actor)
        db.commit()
        reconcile_payment(db, p.id, actor)
        db.refresh(order)
        return order
    if p and p.status == 'pending':
        n = db.execute(update(Payment).where(Payment.id == p.id, Payment.status == 'pending')
                       .values(status='cancelled', settled_at=time.time())).rowcount
        if n == 1:
            _release_hold(db, order.batch_id, p.amount_cents)
            order.status = 'cancelled'
            order.closed_at = time.time()
            _event(db, order.batch_id, order.id, 'order.cancelled', 'release', p.amount_cents, '付款未发出，撤销并释放占用', actor)
            db.commit()
            return order
        db.rollback()
        db.refresh(order)
        return cancel(db, order, actor)  # 付款刚发出，改走在途撤销
    raise HTTPException(409, '单据状态异常，请先对账')


def _start_refund(db, order, payment, actor):
    refund = db.scalar(select(Refund).where(Refund.payment_id == payment.id))
    if not refund:
        refund = Refund(refund_no='REF-' + payment.payment_no, payment_id=payment.id, order_id=order.id,
                        batch_id=order.batch_id, amount_cents=payment.amount_cents, status='pending',
                        created_at=time.time())
        db.add(refund)
        db.flush()
    order.status = 'refunding'
    _event(db, order.batch_id, order.id, 'refund.requested', 'info', refund.amount_cents,
           '已付款撤销，发起退款冲回；退款确认前不释放可赔金额', actor)
    db.flush()
    return refund


def dispatch_refund(db, refund_id, actor='system'):
    r = db.get(Refund, refund_id)
    if not r or r.status != 'pending':
        return r
    payment = db.get(Payment, r.payment_id)
    n = db.execute(update(Refund).where(Refund.id == r.id, Refund.status == 'pending')
                   .values(status='sent', attempts=Refund.attempts + 1, last_attempt_at=time.time())).rowcount
    if n != 1:
        db.rollback()
        return db.get(Refund, refund_id)
    db.commit()  # 发出状态先落库，再调付款端
    try:
        paygate.submit_refund(r.refund_no, payment.payment_no, r.amount_cents)
    except paygate.Rejected as e:
        r.status = 'failed'
        r.note = str(e)[:290]
        r.settled_at = time.time()
        _event(db, r.batch_id, r.order_id, 'refund.failed', 'info', r.amount_cents, f'退款被拒：{str(e)[:200]}', actor)
        db.commit()
        return r
    except paygate.GatewayError as e:
        r.status = 'pending'  # 退款通道故障：留在待发起，退避后重试
        r.note = str(e)[:290]
        if r.attempts <= 1:
            _event(db, r.batch_id, r.order_id, 'refund.failed', 'info', r.amount_cents, '退款通道故障，待重试；确认前不释放可赔金额', actor)
        db.commit()
        return r
    r.note = ''
    db.commit()
    settle_refund(db, r.id, actor)
    return db.get(Refund, refund_id)


def settle_refund(db, refund_id, actor='system'):
    """退款对账：确认后才释放可赔金额。旧回执不改新状态。"""
    r = db.get(Refund, refund_id)
    if not r or r.status not in ('pending', 'sent'):
        return r
    rec = paygate.fetch_refund(r.refund_no)
    if not rec:
        if r.status == 'sent':
            r.status = 'pending'  # 付款端无记录，单号幂等，重发安全
            db.commit()
        return r
    if rec['amount_cents'] != r.amount_cents:
        r.note = '退款对账金额不一致，待人工核对'
        db.commit()
        return r
    r.receipt = rec
    if rec['status'] == 'succeeded':
        r.status = 'succeeded'
        r.settled_at = time.time()
        _mark_refunded(db, r.batch_id, r.amount_cents)
        order = db.get(PayoutOrder, r.order_id)
        if order.status == 'refunding':
            order.status = 'cancelled'
            order.closed_at = time.time()
        _event(db, r.batch_id, r.order_id, 'refund.in', 'in', r.amount_cents, '退款确认，资金划回，释放可赔金额', actor)
        _event(db, r.batch_id, r.order_id, 'order.cancelled', 'info', 0, '退款完成，核销单关闭', actor)
    else:
        r.status = 'failed'
        r.settled_at = time.time()
        _event(db, r.batch_id, r.order_id, 'refund.failed', 'info', r.amount_cents, '退款失败，待重新发起', actor)
    db.commit()
    return r


def advance_order(db, order, actor='system'):
    """消除漂移：撤销中但付款实际未发出 → 直接关闭。"""
    if order.status != 'cancelling':
        return
    p = latest_payment(db, order.id)
    if p and p.status == 'pending':
        n = db.execute(update(Payment).where(Payment.id == p.id, Payment.status == 'pending')
                       .values(status='cancelled', settled_at=time.time())).rowcount
        if n == 1:
            _release_hold(db, order.batch_id, p.amount_cents)
            order.status = 'cancelled'
            order.closed_at = time.time()
            _event(db, order.batch_id, order.id, 'order.cancelled', 'release', p.amount_cents, '对账确认付款未发出，撤销并释放占用', actor)
            db.commit()


# ---- 重试与对账（手动） ----
def retry(db, order, actor):
    st = order.status
    p = latest_payment(db, order.id)
    if st == 'confirmed' and p and p.status == 'pending':
        dispatch_payment(db, p.id, actor)  # 同单重试不新增付款
    elif st in ('paying', 'cancelling') and p:
        reconcile_payment(db, p.id, actor)  # 先对账，不盲目再付
        advance_order(db, db.get(PayoutOrder, order.id), actor)
    elif st == 'refunding':
        r = latest_refund(db, order.id)
        if r and r.status == 'pending':
            dispatch_refund(db, r.id, actor)
        elif r and r.status == 'sent':
            settle_refund(db, r.id, actor)
    elif st == 'failed':
        n = db.execute(update(PayoutOrder).where(PayoutOrder.id == order.id, PayoutOrder.status == 'failed')
                       .values(status='confirmed', closed_at=None)).rowcount
        if n != 1:
            raise HTTPException(409, '单据状态已变化，请刷新')
        if not _hold(db, order.batch_id, order.claim_cents):
            raise HTTPException(409, '可赔余额不足，无法重新发起')
        attempt = (p.attempt if p else 0) + 1
        np = Payment(payment_no=f'PAY-{order.order_no}-A{attempt}', order_id=order.id, batch_id=order.batch_id,
                     amount_cents=order.claim_cents, attempt=attempt, status='pending', created_at=time.time())
        db.add(np)
        db.flush()
        _event(db, order.batch_id, order.id, 'hold', 'hold', order.claim_cents, f'第 {attempt} 次发起付款，重新占用', actor)
        db.commit()
        dispatch_payment(db, np.id, actor)
    else:
        raise HTTPException(409, '当前状态无需重试')
    db.refresh(order)
    return order


def reconcile(db, order, actor):
    p = latest_payment(db, order.id)
    if p and p.status in ('pending', 'sent'):
        reconcile_payment(db, p.id, actor)
    r = latest_refund(db, order.id)
    if r and r.status == 'pending':
        dispatch_refund(db, r.id, actor)
    elif r and r.status == 'sent':
        settle_refund(db, r.id, actor)
    advance_order(db, db.get(PayoutOrder, order.id), actor)
    record(db, actor, 'payout.reconcile', {'order_no': order.order_no})
    db.commit()
    db.refresh(order)
    return order


# ---- 定时清扫与中断恢复 ----
def settle_sweep(db, limit=8, grace=RECEIPT_GRACE_SECONDS, refund_backoff=REFUND_RETRY_SECONDS):
    now = time.time()
    steps = 0
    ids = db.scalars(select(Payment.id).join(PayoutOrder, Payment.order_id == PayoutOrder.id)
                     .where(Payment.status == 'pending', PayoutOrder.status.in_(('confirmed', 'paying'))).limit(limit)).all()
    for i in ids:
        steps += 1
        _safe(lambda i=i: dispatch_payment(db, i, 'worker'), db)
    ids = db.scalars(select(Payment.id).where(Payment.status == 'sent', Payment.sent_at < now - grace).limit(limit)).all()
    for i in ids:
        steps += 1
        _safe(lambda i=i: reconcile_payment(db, i, 'worker'), db)
    ids = db.scalars(select(PayoutOrder.id).where(PayoutOrder.status == 'cancelling').limit(limit)).all()
    for i in ids:
        steps += 1
        _safe(lambda i=i: advance_order(db, db.get(PayoutOrder, i), 'worker'), db)
    ids = db.scalars(select(Refund.id).where(Refund.status == 'pending',
                                             (Refund.last_attempt_at == None) | (Refund.last_attempt_at < now - refund_backoff)).limit(limit)).all()
    for i in ids:
        steps += 1
        _safe(lambda i=i: dispatch_refund(db, i, 'worker'), db)
    ids = db.scalars(select(Refund.id).where(Refund.status == 'sent').limit(limit)).all()
    for i in ids:
        steps += 1
        _safe(lambda i=i: settle_refund(db, i, 'worker'), db)
    return steps


def _safe(fn, db):
    try:
        fn()
    except Exception:
        db.rollback()
        logging.exception('Payout settle step failed')


def recover(db):
    """中断后恢复未结付款和退款：登记审计并立即清扫（无宽限/退避）。"""
    pays = db.scalar(select(func.count()).select_from(Payment).where(Payment.status.in_(('pending', 'sent'))))
    refs = db.scalar(select(func.count()).select_from(Refund).where(Refund.status.in_(('pending', 'sent'))))
    if pays or refs:
        record(db, 'worker', 'payout.recovered', {'unsettled_payments': pays, 'unsettled_refunds': refs})
        db.commit()
        settle_sweep(db, grace=0, refund_backoff=0)
    return {'unsettled_payments': pays, 'unsettled_refunds': refs}
