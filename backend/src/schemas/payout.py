from pydantic import BaseModel, Field


class BatchInput(BaseModel):
    code: str = Field(min_length=3, max_length=40)
    title: str = Field(min_length=2, max_length=160)
    approved_loss: float = Field(gt=0, description='核定损失（元）')


class PayoutOrderInput(BaseModel):
    batch_id: int
    claim_amount: float = Field(gt=0, description='申报金额（元）')
    investigation_ids: list[int] = Field(min_length=1, description='所据调查（已批准分析任务）')
    note: str = Field(default='', max_length=300)
    order_no: str | None = Field(default=None, max_length=40)  # 仅种子数据指定，保证幂等


class FaultInput(BaseModel):
    drop_receipt: bool | None = None
    fail_refund: bool | None = None


class GatewayPaymentInput(BaseModel):
    payment_no: str = Field(min_length=3, max_length=48)
    amount: float = Field(gt=0)
    memo: str = Field(default='', max_length=200)


class GatewayRefundInput(BaseModel):
    refund_no: str = Field(min_length=3, max_length=48)
    payment_no: str = Field(min_length=3, max_length=48)
    amount: float = Field(gt=0)
