from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import CargoBatch, PayoutOrder, Payment, Refund, FundEvent, Job
from src.schemas.payout import BatchInput, PayoutOrderInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import payouts
from src.services.audit import record
from src.utils.serialization import batch_dict, payout_order_dict, payment_dict, refund_dict, fund_event_dict

router = APIRouter()


def _get_order(db, id):
    o = db.get(PayoutOrder, id)
    if not o:
        raise HTTPException(404, '赔付核销单不存在')
    return o


@router.get('/batches')
def batches(db=Depends(get_db), u=Depends(current_user)):
    return [batch_dict(b) for b in db.scalars(select(CargoBatch).order_by(CargoBatch.id))]


@router.post('/batches', status_code=201)
def create_batch(data: BatchInput, db=Depends(get_db), u=Depends(admin_only)):
    b = payouts.create_batch(db, data, u)
    record(db, u.email, 'batch.register', {'code': b.code, 'approved_loss_cents': b.approved_loss_cents})
    db.commit()
    return batch_dict(b)


@router.get('/batches/{id}/events')
def batch_events(id: int, db=Depends(get_db), u=Depends(current_user)):
    if not db.get(CargoBatch, id):
        raise HTTPException(404, '货批不存在')
    rows = db.scalars(select(FundEvent).where(FundEvent.batch_id == id).order_by(FundEvent.id.desc()).limit(100))
    return [fund_event_dict(e) for e in rows]


@router.get('/payout-orders')
def orders(db=Depends(get_db), u=Depends(current_user)):
    codes = {b.id: b.code for b in db.scalars(select(CargoBatch))}
    rows = db.scalars(select(PayoutOrder).order_by(PayoutOrder.id.desc()).limit(200))
    return [payout_order_dict(o, codes.get(o.batch_id)) for o in rows]


@router.post('/payout-orders', status_code=201)
def create_order(data: PayoutOrderInput, db=Depends(get_db), u=Depends(can_write)):
    o = payouts.create_order(db, data, u)
    record(db, u.email, 'payout.create', {'order_no': o.order_no, 'batch_id': o.batch_id, 'claim_cents': o.claim_cents})
    db.commit()
    return payout_order_dict(o, db.get(CargoBatch, o.batch_id).code)


@router.get('/payout-orders/{id}')
def order_detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    o = _get_order(db, id)
    payments = db.scalars(select(Payment).where(Payment.order_id == id).order_by(Payment.id))
    refunds = db.scalars(select(Refund).where(Refund.order_id == id).order_by(Refund.id))
    events = db.scalars(select(FundEvent).where(FundEvent.order_id == id).order_by(FundEvent.id.desc()).limit(100))
    investigations = [{'id': j.id, 'name': j.name, 'approved': j.approved}
                      for j in db.scalars(select(Job).where(Job.id.in_(o.investigation_ids or [])))]
    return {'order': payout_order_dict(o, db.get(CargoBatch, o.batch_id).code),
            'batch': batch_dict(db.get(CargoBatch, o.batch_id)),
            'payments': [payment_dict(p) for p in payments],
            'refunds': [refund_dict(r) for r in refunds],
            'events': [fund_event_dict(e) for e in events],
            'investigations': investigations}


@router.post('/payout-orders/{id}/confirm')
def confirm(id: int, db=Depends(get_db), u=Depends(admin_only)):
    o = payouts.confirm(db, _get_order(db, id), u.email)
    return payout_order_dict(o, db.get(CargoBatch, o.batch_id).code)


@router.post('/payout-orders/{id}/cancel')
def cancel(id: int, db=Depends(get_db), u=Depends(admin_only)):
    o = _get_order(db, id)
    o = payouts.cancel(db, o, u.email)
    record(db, u.email, 'payout.cancel', {'order_no': o.order_no, 'status': o.status})
    db.commit()
    return payout_order_dict(o, db.get(CargoBatch, o.batch_id).code)


@router.post('/payout-orders/{id}/retry')
def retry(id: int, db=Depends(get_db), u=Depends(admin_only)):
    o = payouts.retry(db, _get_order(db, id), u.email)
    record(db, u.email, 'payout.retry', {'order_no': o.order_no, 'status': o.status})
    db.commit()
    return payout_order_dict(o, db.get(CargoBatch, o.batch_id).code)


@router.post('/payout-orders/{id}/reconcile')
def reconcile(id: int, db=Depends(get_db), u=Depends(admin_only)):
    o = payouts.reconcile(db, _get_order(db, id), u.email)
    return payout_order_dict(o, db.get(CargoBatch, o.batch_id).code)
