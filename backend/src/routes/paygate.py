"""本地付款端 HTTP 面：供页面查看台账、演练丢回执与退款失败。

业务侧（src.services.payouts）通过 src.services.paygate 直接调用同一核心；
这里暴露的接口用于演练与验收，例如同号改金额拒收、回执丢失后对账。
"""
from fastapi import APIRouter, Depends, HTTPException
from src.middlewares.auth import current_user, admin_only
from src.schemas.payout import FaultInput, GatewayPaymentInput, GatewayRefundInput
from src.services import paygate
from src.services.payouts import to_cents
from src.utils.serialization import gateway_payment_dict, gateway_refund_dict

router = APIRouter(prefix='/paygate')


@router.get('/state')
def state(u=Depends(current_user)):
    data = paygate.ledger()
    return {'faults': data['faults'],
            'payments': [gateway_payment_dict(p) for p in data['payments']],
            'refunds': [gateway_refund_dict(r) for r in data['refunds']]}


@router.put('/faults')
def faults(data: FaultInput, u=Depends(admin_only)):
    return paygate.set_faults(drop_receipt=data.drop_receipt, fail_refund=data.fail_refund)


@router.post('/payments', status_code=201)
def submit_payment(data: GatewayPaymentInput, u=Depends(admin_only)):
    try:
        return gateway_payment_dict(paygate.submit_payment(data.payment_no, to_cents(data.amount, '付款金额'), data.memo))
    except paygate.Rejected as e:
        raise HTTPException(409, str(e))


@router.get('/payments/{payment_no}')
def payment(payment_no: str, u=Depends(current_user)):
    rec = paygate.fetch_payment(payment_no)
    if not rec:
        raise HTTPException(404, '付款端无此付款记录')
    return gateway_payment_dict(rec)


@router.get('/payments/{payment_no}/receipt')
def receipt(payment_no: str, u=Depends(current_user)):
    try:
        rec = paygate.fetch_receipt(payment_no)
    except paygate.ReceiptLost as e:
        raise HTTPException(503, str(e))
    if not rec:
        raise HTTPException(404, '付款端无此付款记录')
    return gateway_payment_dict(rec)


@router.post('/refunds', status_code=201)
def submit_refund(data: GatewayRefundInput, u=Depends(admin_only)):
    try:
        return gateway_refund_dict(paygate.submit_refund(data.refund_no, data.payment_no, to_cents(data.amount, '退款金额')))
    except paygate.Rejected as e:
        raise HTTPException(409, str(e))
    except paygate.GatewayError as e:
        raise HTTPException(502, str(e))


@router.get('/refunds/{refund_no}')
def refund(refund_no: str, u=Depends(current_user)):
    rec = paygate.fetch_refund(refund_no)
    if not rec:
        raise HTTPException(404, '付款端无此退款记录')
    return gateway_refund_dict(rec)
