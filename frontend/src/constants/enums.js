export const Role={admin:'业务负责人',analyst:'分析员',viewer:'观察员'};
export const JobStatus={queued:'排队中',running:'计算中',completed:'已完成',failed:'执行失败'};
export const PayoutStatus={draft:'待财务确认',confirmed:'已确认·待付款',paying:'付款在途',paid:'已付款',cancelling:'撤销中·等对账',refunding:'退款中',cancelled:'已撤销',failed:'付款失败'};
export const PaymentStatus={pending:'待发送',sent:'待回执',succeeded:'付款成功',failed:'付款失败',cancelled:'未发出'};
export const RefundStatus={pending:'待发起',sent:'退款在途',succeeded:'已退款',failed:'退款失败'};
export const FundKind={'batch.register':'登记货批','order.created':'开单',hold:'占用可赔','pay.dispatch':'付款发出','pay.out':'付款成功·资金划出','pay.failed':'付款失败·释放','pay.receipt_lost':'回执丢失·待对账','pay.reconcile':'对账','pay.mismatch':'对账金额异常','refund.requested':'发起退款','refund.failed':'退款失败·待重试','refund.in':'退款冲回·资金划回','order.cancelled':'核销单关闭','cancel.requested':'撤销申请'};
