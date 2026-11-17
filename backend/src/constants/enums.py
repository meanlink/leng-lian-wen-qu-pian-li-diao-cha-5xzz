from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class PayoutStatus(str, Enum):
    draft = 'draft'  # 待财务确认
    confirmed = 'confirmed'  # 已确认待付款
    paying = 'paying'  # 付款在途待回执
    paid = 'paid'  # 已付款
    cancelling = 'cancelling'  # 撤销中，等对账
    refunding = 'refunding'  # 退款中
    cancelled = 'cancelled'  # 已撤销
    failed = 'failed'  # 付款失败
class PaymentStatus(str, Enum):
    pending = 'pending'  # 待发送
    sent = 'sent'  # 已发送待回执
    succeeded = 'succeeded'
    failed = 'failed'
    cancelled = 'cancelled'  # 未发出即撤销
class RefundStatus(str, Enum):
    pending = 'pending'
    sent = 'sent'
    succeeded = 'succeeded'
    failed = 'failed'
