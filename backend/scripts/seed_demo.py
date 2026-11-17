import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, CargoBatch, PayoutOrder
from src.services.business import metadata, seed_records, analyze
from src.services.reports import deliver
from src.services import payouts
from src.schemas.payout import PayoutOrderInput, BatchInput
from src.utils.security import hash_password
from src.utils.serialization import checksum
def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            admin=db.scalar(select(User).where(User.role=='admin'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        db.commit()
        seed_payouts(db)
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
def seed_payouts(db):
    """演示货批与核销单：自然键（货批号/单号）防重复，不覆盖用户修改。"""
    admin=db.scalar(select(User).where(User.role=='admin'))
    baseline=db.scalar(select(Job).where(Job.approved==True).order_by(Job.id))
    batches={}
    for code,title,loss in [('LOT-2602-A','沪东 A 线 · 生物试剂 48 箱',80000),('LOT-2602-B','沪东 B 线 · 生物试剂 36 箱',120000)]:
        b=db.scalar(select(CargoBatch).where(CargoBatch.code==code))
        if not b:
            b=payouts.create_batch(db,BatchInput(code=code,title=title,approved_loss=loss),admin)
        batches[code]=b
    db.flush()
    if baseline and not db.scalar(select(PayoutOrder).where(PayoutOrder.order_no=='PO-SEED-0001')):
        o=payouts.create_order(db,PayoutOrderInput(batch_id=batches['LOT-2602-B'].id,claim_amount=30000,
            investigation_ids=[baseline.id],note='B 线超温批次首笔赔付',order_no='PO-SEED-0001'),admin)
        db.flush()
        payouts.confirm(db,o,'seed')  # 确认后即付款成功，演示累计实付占用
    if baseline and not db.scalar(select(PayoutOrder).where(PayoutOrder.order_no=='PO-SEED-0002')):
        payouts.create_order(db,PayoutOrderInput(batch_id=batches['LOT-2602-B'].id,claim_amount=45000,
            investigation_ids=[baseline.id],note='B 线保温包装复核赔付（待财务确认）',order_no='PO-SEED-0002'),admin)
    db.flush()
if __name__=='__main__':seed()
