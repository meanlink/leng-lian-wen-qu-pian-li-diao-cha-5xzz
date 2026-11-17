"""本地付款端：模拟外部付款通道，独立会话提交（付款端状态不随业务回滚）。

- 付款/退款按单号幂等：同号同额返回原记录，同号改金额拒收。
- 回执与台账分离：回执可丢失（演练开关），台账查询（对账）始终可用。
- 演练开关：drop_receipt 丢回执；fail_refund 退款通道故障。
"""
import time
from sqlalchemy import select, func
from src.config.database import Session
from src.models import GatewayPayment, GatewayRefund, GatewayFault


class GatewayError(Exception):
    """付款端不可用或故障，稍后重试。"""


class ReceiptLost(GatewayError):
    """付款已成但回执丢失：先对账，不盲目再付。"""


class Rejected(GatewayError):
    """付款端拒收（如同号改金额），属确定性失败。"""


def _faults(db):
    f = db.get(GatewayFault, 1)
    if not f:
        f = GatewayFault(id=1, drop_receipt=False, fail_refund=False, updated_at=time.time())
        db.add(f)
        try:
            db.commit()
        except Exception:  # 并发首建：回滚后取对方已建行
            db.rollback()
            f = db.get(GatewayFault, 1)
    return f


def get_faults():
    with Session() as db:
        f = _faults(db)
        return {'drop_receipt': f.drop_receipt, 'fail_refund': f.fail_refund, 'updated_at': f.updated_at}


def set_faults(drop_receipt=None, fail_refund=None):
    with Session() as db:
        f = _faults(db)
        if drop_receipt is not None:
            f.drop_receipt = bool(drop_receipt)
        if fail_refund is not None:
            f.fail_refund = bool(fail_refund)
        f.updated_at = time.time()
        db.commit()
        return {'drop_receipt': f.drop_receipt, 'fail_refund': f.fail_refund, 'updated_at': f.updated_at}


def _payment_dict(p):
    return {'payment_no': p.payment_no, 'amount_cents': p.amount_cents, 'memo': p.memo,
            'status': p.status, 'receipt_seq': p.receipt_seq, 'created_at': p.created_at}


def _refund_dict(r):
    return {'refund_no': r.refund_no, 'payment_no': r.payment_no, 'amount_cents': r.amount_cents,
            'status': r.status, 'receipt_seq': r.receipt_seq, 'created_at': r.created_at}


def submit_payment(payment_no, amount_cents, memo=''):
    """受理付款。同号同额幂等返回；同号改金额拒收。成功即入账，回执另行领取。"""
    with Session() as db:
        existing = db.scalar(select(GatewayPayment).where(GatewayPayment.payment_no == payment_no))
        if existing:
            if existing.amount_cents != amount_cents:
                raise Rejected(f'付款单号 {payment_no} 已存在且金额不一致，拒收')
            return _payment_dict(existing)
        p = GatewayPayment(payment_no=payment_no, amount_cents=amount_cents, memo=memo,
                           status='succeeded', created_at=time.time())
        db.add(p)
        db.flush()
        p.receipt_seq = p.id
        db.commit()
        return _payment_dict(p)


def fetch_payment(payment_no):
    """对账：查付款端台账，不受回执开关影响。"""
    with Session() as db:
        p = db.scalar(select(GatewayPayment).where(GatewayPayment.payment_no == payment_no))
        return _payment_dict(p) if p else None


def fetch_receipt(payment_no):
    """领取付款回执；丢回执开关打开时表现为回执丢失。"""
    if get_faults()['drop_receipt']:
        raise ReceiptLost(f'付款 {payment_no} 回执丢失，请对账确认')
    with Session() as db:
        p = db.scalar(select(GatewayPayment).where(GatewayPayment.payment_no == payment_no))
        if not p:
            return None
        return {**_payment_dict(p), 'kind': 'payment.receipt', 'issued_at': time.time()}


def submit_refund(refund_no, payment_no, amount_cents):
    """受理退款。同号幂等；退款开关打开时通道故障；累计退款不超原付款。"""
    if get_faults()['fail_refund']:
        raise GatewayError('退款通道故障（演练中），请稍后重试')
    with Session() as db:
        existing = db.scalar(select(GatewayRefund).where(GatewayRefund.refund_no == refund_no))
        if existing:
            if existing.amount_cents != amount_cents:
                raise Rejected(f'退款单号 {refund_no} 已存在且金额不一致，拒收')
            return _refund_dict(existing)
        pay = db.scalar(select(GatewayPayment).where(GatewayPayment.payment_no == payment_no))
        if not pay or pay.status != 'succeeded':
            raise Rejected(f'原付款 {payment_no} 不存在或未成功，无法退款')
        refunded = db.scalar(select(func.coalesce(func.sum(GatewayRefund.amount_cents), 0))
                             .where(GatewayRefund.payment_no == payment_no, GatewayRefund.status == 'succeeded'))
        if refunded + amount_cents > pay.amount_cents:
            raise Rejected(f'累计退款将超出原付款 {payment_no} 金额，拒收')
        r = GatewayRefund(refund_no=refund_no, payment_no=payment_no, amount_cents=amount_cents,
                          status='succeeded', created_at=time.time())
        db.add(r)
        db.flush()
        r.receipt_seq = r.id
        db.commit()
        return _refund_dict(r)


def fetch_refund(refund_no):
    """对账：查退款台账。"""
    with Session() as db:
        r = db.scalar(select(GatewayRefund).where(GatewayRefund.refund_no == refund_no))
        return _refund_dict(r) if r else None


def ledger():
    """付款端全量台账，供页面对照资金去向。"""
    with Session() as db:
        payments = [_payment_dict(p) for p in db.scalars(select(GatewayPayment).order_by(GatewayPayment.id.desc()).limit(100))]
        refunds = [_refund_dict(r) for r in db.scalars(select(GatewayRefund).order_by(GatewayRefund.id.desc()).limit(100))]
        return {'faults': get_faults(), 'payments': payments, 'refunds': refunds}
