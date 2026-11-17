import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def yuan(cents):
    return None if cents is None else round(cents/100,2)
def batch_dict(b):
    return {'id':b.id,'code':b.code,'title':b.title,'approved_loss':yuan(b.approved_loss_cents),
            'paid':yuan(b.paid_cents),'held':yuan(b.held_cents),
            'available':yuan(b.approved_loss_cents-b.paid_cents-b.held_cents),'created_at':b.created_at}
def payout_order_dict(o,batch_code=None):
    d={k:getattr(o,k) for k in ['id','order_no','batch_id','investigation_ids','note','status','created_at','confirmed_at','closed_at']}
    d['claim_amount']=yuan(o.claim_cents)
    d['batch_code']=batch_code
    return d
def payment_dict(p):
    d={k:getattr(p,k) for k in ['id','payment_no','order_id','attempt','status','receipt_seq','note','created_at','sent_at','settled_at']}
    d['amount']=yuan(p.amount_cents)
    return d
def refund_dict(r):
    d={k:getattr(r,k) for k in ['id','refund_no','payment_id','order_id','attempts','status','note','created_at','settled_at']}
    d['amount']=yuan(r.amount_cents)
    return d
def fund_event_dict(e):
    return {'id':e.id,'batch_id':e.batch_id,'order_id':e.order_id,'kind':e.kind,'direction':e.direction,
            'amount':yuan(e.amount_cents),'available_after':yuan(e.available_after_cents),'note':e.note,'actor':e.actor,'at':e.at}
def gateway_payment_dict(p):
    return {'payment_no':p['payment_no'],'amount':yuan(p['amount_cents']),'memo':p['memo'],'status':p['status'],'receipt_seq':p['receipt_seq'],'created_at':p['created_at']}
def gateway_refund_dict(r):
    return {'refund_no':r['refund_no'],'payment_no':r['payment_no'],'amount':yuan(r['amount_cents']),'status':r['status'],'receipt_seq':r['receipt_seq'],'created_at':r['created_at']}
