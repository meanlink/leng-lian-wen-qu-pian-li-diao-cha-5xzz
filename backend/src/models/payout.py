from sqlalchemy import String, Double, ForeignKey, Boolean, BigInteger, JSON
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class CargoBatch(Base):
    """货批：核定损失与赔付余额的唯一权威。金额一律以分存储，保证任何库上精确。"""
    __tablename__ = 'cargo_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    approved_loss_cents: Mapped[int] = mapped_column(BigInteger)  # 核定损失（分）
    paid_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # 累计实付（付款成功 − 退款确认）
    held_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # 在途占用（已确认未完结）
    created_at: Mapped[float] = mapped_column(Double)


class PayoutOrder(Base):
    """赔付核销单：登记货批、申报金额与所据调查。"""
    __tablename__ = 'payout_orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('cargo_batches.id'))
    claim_cents: Mapped[int] = mapped_column(BigInteger)  # 申报金额（分），确认后不可改
    investigation_ids: Mapped[list] = mapped_column(JSON, default=list)  # 所据调查（已批准分析任务）
    note: Mapped[str] = mapped_column(String(300), default='')
    status: Mapped[str] = mapped_column(String(20), default='draft')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    confirmed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    closed_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class Payment(Base):
    """付款单：payment_no 为幂等键，同单重试复用、同号改金额拒收。"""
    __tablename__ = 'payout_payments'
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_no: Mapped[str] = mapped_column(String(48), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('payout_orders.id'))
    batch_id: Mapped[int] = mapped_column(ForeignKey('cargo_batches.id'))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    attempt: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending/sent/succeeded/failed/cancelled
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    receipt_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 已应用回执序号，旧回执不改新状态
    note: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[float] = mapped_column(Double)
    sent_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    settled_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class Refund(Base):
    """退款单：已付订单撤销时以退款冲回，确认前不释放可赔金额。"""
    __tablename__ = 'payout_refunds'
    id: Mapped[int] = mapped_column(primary_key=True)
    refund_no: Mapped[str] = mapped_column(String(48), unique=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey('payout_payments.id'))
    order_id: Mapped[int] = mapped_column(ForeignKey('payout_orders.id'))
    batch_id: Mapped[int] = mapped_column(ForeignKey('cargo_batches.id'))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending/sent/succeeded/failed
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[float] = mapped_column(Double)
    last_attempt_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    settled_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class FundEvent(Base):
    """资金流水：查资金去向。available_after 为事件后货批可赔余额快照。"""
    __tablename__ = 'fund_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('cargo_batches.id'))
    order_id: Mapped[int | None] = mapped_column(ForeignKey('payout_orders.id'), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    direction: Mapped[str] = mapped_column(String(8), default='info')  # hold/out/in/release/info
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    available_after_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default='')
    actor: Mapped[str] = mapped_column(String(150), default='system')
    at: Mapped[float] = mapped_column(Double)


class GatewayPayment(Base):
    """本地付款端台账（模拟外部付款端，独立提交）。"""
    __tablename__ = 'gateway_payments'
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_no: Mapped[str] = mapped_column(String(48), unique=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    memo: Mapped[str] = mapped_column(String(200), default='')
    status: Mapped[str] = mapped_column(String(20), default='succeeded')
    receipt_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[float] = mapped_column(Double)


class GatewayRefund(Base):
    __tablename__ = 'gateway_refunds'
    id: Mapped[int] = mapped_column(primary_key=True)
    refund_no: Mapped[str] = mapped_column(String(48), unique=True)
    payment_no: Mapped[str] = mapped_column(String(48))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default='succeeded')
    receipt_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[float] = mapped_column(Double)


class GatewayFault(Base):
    """演练开关：丢回执、退款失败。单行。"""
    __tablename__ = 'gateway_faults'
    id: Mapped[int] = mapped_column(primary_key=True)
    drop_receipt: Mapped[bool] = mapped_column(Boolean, default=False)
    fail_refund: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[float] = mapped_column(Double, default=0)
