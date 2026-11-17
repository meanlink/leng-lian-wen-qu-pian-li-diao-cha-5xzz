import {jobs,payouts,paygate} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {route} from '../router/index.js';
import {PayoutStatus,PaymentStatus,RefundStatus,FundKind} from '../constants/enums.js';
import {esc,date,notify,money} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

const pill=v=>'<span class="pill p-'+esc(v)+'">'+esc(PayoutStatus[v]||v)+'</span>';
const active=o=>['confirmed','paying','cancelling','refunding'].includes(o.status);
const kindLabel=k=>FundKind[k]||k;
const signed=e=>{const m=money(e.amount);if(e.direction==='out')return '− '+m;if(e.direction==='in')return '+ '+m;return m;};

function batchCards(batches,selectedId){
 if(!batches.length)return '<p class="empty">尚无货批。请先登记货批与核定损失。</p>';
 return '<div class="batch-cards">'+batches.map(b=>'<button class="balance-card'+(b.id===selectedId?' selected':'')+'" data-batch="'+b.id+'"><span class="code">'+esc(b.code)+'</span><span class="title">'+esc(b.title)+'</span><span class="figures"><span>核定损失<strong>'+money(b.approved_loss)+'</strong></span><span>累计实付<strong>'+money(b.paid)+'</strong></span><span>在途占用<strong>'+money(b.held)+'</strong></span><span class="avail">可赔余额<strong>'+money(b.available)+'</strong></span></span></button>').join('')+'</div>';
}
function orderRow(o,isAdmin,detailId){
 const acts=[];
 acts.push('<button class="text-button" data-detail="'+o.id+'">资金详情</button>');
 if(isAdmin&&o.status==='draft')acts.push('<button class="text-button" data-confirm="'+o.id+'">确认</button>');
 if(isAdmin&&['draft','confirmed','paying','paid'].includes(o.status))acts.push('<button class="text-button" data-cancel="'+o.id+'">撤销</button>');
 if(isAdmin&&['confirmed','paying','cancelling','refunding','failed'].includes(o.status))acts.push('<button class="text-button" data-retry="'+o.id+'">重试</button>');
 if(isAdmin&&['paying','cancelling','refunding'].includes(o.status))acts.push('<button class="text-button" data-reconcile="'+o.id+'">对账</button>');
 return '<tr class="'+(detailId===o.id?'row-selected':'')+'"><td>'+esc(o.order_no)+'</td><td>'+esc(o.batch_code||'')+'</td><td>'+money(o.claim_amount)+'</td><td>'+(o.investigation_ids||[]).length+' 份</td><td>'+pill(o.status)+'</td><td>'+date(o.created_at)+'</td><td class="acts">'+acts.join('')+'</td></tr>';
}
function detailPanel(d){
 const o=d.order;
 const payRows=d.payments.map(p=>'<tr><td>'+esc(p.payment_no)+'</td><td>'+money(p.amount)+'</td><td>第 '+p.attempt+' 次</td><td>'+esc(PaymentStatus[p.status]||p.status)+'</td><td>'+(p.receipt_seq??'—')+'</td><td>'+esc(p.note||'')+'</td></tr>').join('');
 const refRows=d.refunds.map(r=>'<tr><td>'+esc(r.refund_no)+'</td><td>'+money(r.amount)+'</td><td>'+r.attempts+' 次</td><td>'+esc(RefundStatus[r.status]||r.status)+'</td><td>'+esc(r.note||'')+'</td></tr>').join('');
 return '<section class="panel detail-panel"><div class="section-title"><h2>资金去向 · '+esc(o.order_no)+'</h2><span>'+esc(o.batch_code)+' · 申报 '+money(o.claim_amount)+' · '+esc(PayoutStatus[o.status]||o.status)+'</span></div>'
 +'<div class="detail-grid"><div><p class="eyebrow">所据调查（获批）</p><ol class="questions">'+d.investigations.map(j=>'<li>'+esc(j.name)+'</li>').join('')+'</ol>'+(o.note?'<p class="hint">'+esc(o.note)+'</p>':'')+'</div>'
 +'<div><p class="eyebrow">付款单</p><div class="table-wrap"><table><thead><tr><th>付款单号</th><th>金额</th><th>尝试</th><th>状态</th><th>回执序号</th><th>备注</th></tr></thead><tbody>'+payRows+'</tbody></table></div>'
 +(d.refunds.length?'<p class="eyebrow">退款单</p><div class="table-wrap"><table><thead><tr><th>退款单号</th><th>金额</th><th>尝试</th><th>状态</th><th>备注</th></tr></thead><tbody>'+refRows+'</tbody></table></div>':'')+'</div></div>'
 +'<p class="eyebrow">资金流水</p><ul class="timeline fund">'+d.events.map(e=>'<li><strong>'+esc(kindLabel(e.kind))+'</strong><span>'+esc(e.note)+'</span><span>'+signed(e)+' · 余 '+money(e.available_after)+'</span><span>'+esc(e.actor)+' · '+date(e.at)+'</span></li>').join('')+'</ul></section>';
}
function gatePanel(gate,isAdmin){
 const f=gate.faults;
 const sw=(key,on,label)=>'<div class="fault"><span>'+label+'</span><button class="button small" data-fault="'+key+'" data-on="'+(on?0:1)+'" '+(isAdmin?'':'disabled')+'>'+(on?'演练中 · 点击恢复':'正常 · 点击演练')+'</button></div>';
 const rows=gate.payments.map(p=>'<tr><td>'+esc(p.payment_no)+'</td><td>'+money(p.amount)+'</td><td>'+esc(p.status)+'</td><td>'+p.receipt_seq+'</td></tr>').join('');
 const rrows=gate.refunds.map(r=>'<tr><td>'+esc(r.refund_no)+'</td><td>'+esc(r.payment_no)+'</td><td>'+money(r.amount)+'</td><td>'+esc(r.status)+'</td></tr>').join('');
 return '<section class="panel"><div class="section-title"><h2>本地付款端</h2><span>独立台账 · 可演练故障</span></div>'
 +sw('drop_receipt',f.drop_receipt,'丢回执：付款已成但回执丢失')+sw('fail_refund',f.fail_refund,'退款失败：退款通道故障')
 +'<p class="hint">演练路径：打开「丢回执」后确认核销单 → 付款在途 → 对账后确认付款，不会重复付款；打开「退款失败」后撤销已付单 → 退款待重试，期间可赔余额不释放。</p>'
 +'<p class="eyebrow">付款端台账</p><div class="table-wrap"><table><thead><tr><th>付款单号</th><th>金额</th><th>状态</th><th>回执序号</th></tr></thead><tbody>'+(rows||'<tr><td colspan="4">暂无</td></tr>')+'</tbody></table></div>'
 +(gate.refunds.length?'<p class="eyebrow">退款台账</p><div class="table-wrap"><table><thead><tr><th>退款单号</th><th>原付款单号</th><th>金额</th><th>状态</th></tr></thead><tbody>'+rrows+'</tbody></table></div>':'')+'</section>';
}

export async function payoutPage(id){
 const [batches,orders,allJobs,gate]=await Promise.all([payouts.batches(),payouts.list(),jobs.list(),paygate.state()]);
 workspace.payoutBatches=batches;
 const approved=allJobs.filter(j=>j.approved&&j.status==='completed');
 const selected=batches.find(b=>b.id===workspace.selectedBatch)||batches[0];
 workspace.selectedBatch=selected?selected.id:null;
 const events=selected?await payouts.events(selected.id):[];
 const isAdmin=session.user.role==='admin',canWrite=session.user.role!=='viewer';
 const detailId=id?Number(id):null;
 let detail=null;
 if(detailId){try{detail=await payouts.get(detailId);}catch(e){}}
 const orderRows=orders.map(o=>orderRow(o,isAdmin,detailId)).join('');
 return heading('06 / PAYOUTS','赔付核销与资金去向','同一货批被多份获批调查引用时，按核定损失控制累计实付。确认、付款、对账、撤销、退款全程留痕。','<button class="button" id="refresh-payouts">刷新 ↻</button>')
 +'<section class="panel"><div class="section-title"><h2>货批余额</h2><span>同批累计实付不超核定损失 · 点击货批查看资金流水</span></div>'+batchCards(batches,workspace.selectedBatch)+'</section>'
 +'<div class="payout-grid"><section class="panel"><div class="section-title"><h2>开具核销单</h2></div><form id="payout-form"><label>货批<select name="batch_id" required>'+batches.map(b=>'<option value="'+b.id+'">'+esc(b.code)+' · 可赔 '+money(b.available)+'</option>').join('')+'</select></label><label>申报金额（元）<input name="claim_amount" type="number" step="0.01" min="0.01" required placeholder="例如 30000.00"></label><fieldset class="checks"><legend>所据调查（仅已批准分析可作为依据）</legend>'+(approved.length?approved.map(j=>'<label class="check"><input type="checkbox" name="investigation_ids" value="'+j.id+'">'+esc(j.name)+'</label>').join(''):'<p class="hint">尚无获批调查，请先在结果复核页批准分析。</p>')+'</fieldset><label>备注<input name="note" maxlength="300" placeholder="赔付事由"></label><button type="submit" class="primary" '+(canWrite&&batches.length&&approved.length?'':'disabled')+'>开单（待财务确认）</button><p class="hint">开单不占用余额；财务确认后占用并付款。确认与撤销仅业务负责人可操作。</p></form>'
 +(isAdmin?'<div class="section-title"><h2>登记货批</h2></div><form id="batch-form"><label>货批号<input name="code" required minlength="3" maxlength="40" placeholder="例如 LOT-2602-C"></label><label>货批说明<input name="title" required minlength="2" maxlength="160" placeholder="例如 沪东 C 线 · 生物试剂 20 箱"></label><label>核定损失（元）<input name="approved_loss" type="number" step="0.01" min="0.01" required placeholder="例如 100000.00"></label><button type="submit" class="primary">登记货批</button></form>':'')+'</section>'
 +'<section class="panel"><div class="section-title"><h2>核销单</h2><span>'+orders.length+' 单 · '+(orders.filter(active).length?'有在途单据，页面将自动刷新':'')+'</span></div><div class="table-wrap"><table><thead><tr><th>单号</th><th>货批</th><th>申报金额</th><th>依据</th><th>状态</th><th>开单时间</th><th>操作</th></tr></thead><tbody>'+(orderRows||'<tr><td colspan="7">暂无核销单</td></tr>')+'</tbody></table></div></section></div>'
 +(detail?detailPanel(detail):'')
 +'<div class="payout-grid"><section class="panel"><div class="section-title"><h2>资金流水'+(selected?' · '+esc(selected.code):'')+'</h2><span>货批全量资金去向</span></div><ul class="timeline fund">'+(events.map(e=>'<li><strong>'+esc(kindLabel(e.kind))+'</strong><span>'+esc(e.note)+'</span><span>'+signed(e)+' · 余 '+money(e.available_after)+'</span><span>'+esc(e.actor)+' · '+date(e.at)+'</span></li>').join('')||'<li><strong>暂无资金事件</strong></li>')+'</ul></section>'
 +gatePanel(gate,isAdmin)+'</div>';
}

export function bindPayouts(refresh){
 document.querySelector('#refresh-payouts').onclick=refresh;
 document.querySelectorAll('[data-batch]').forEach(b=>b.onclick=()=>{workspace.selectedBatch=Number(b.dataset.batch);refresh();});
 document.querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>{location.hash='#/payouts/'+b.dataset.detail;});
 const act=(attr,fn,ok)=>document.querySelectorAll('['+attr+']').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await fn(b.getAttribute(attr));notify(ok);}catch(e){notify(e.message,true);}await refresh();});
 act('data-confirm',id=>payouts.confirm(id),'已确认，付款处理中');
 act('data-cancel',id=>payouts.cancel(id),'撤销已受理');
 act('data-retry',id=>payouts.retry(id),'已重试（同单不新增付款）');
 act('data-reconcile',id=>payouts.reconcile(id),'对账完成');
 document.querySelectorAll('[data-fault]').forEach(b=>b.onclick=async()=>{try{const body={};body[b.dataset.fault]=b.dataset.on==='1';await paygate.faults(body);notify('付款端演练开关已更新');await refresh();}catch(e){notify(e.message,true);}});
 submit(document.querySelector('#payout-form'),async f=>{await payouts.create({batch_id:Number(f.get('batch_id')),claim_amount:Number(f.get('claim_amount')),investigation_ids:f.getAll('investigation_ids').map(Number),note:f.get('note')||''});notify('核销单已开具，待财务确认');await refresh();});
 const bf=document.querySelector('#batch-form');
 if(bf)submit(bf,async f=>{await payouts.createBatch({code:f.get('code'),title:f.get('title'),approved_loss:Number(f.get('approved_loss'))});notify('货批已登记');await refresh();});
 clearTimeout(workspace.payoutTimer);
 payouts.list().then(list=>{if(list.some(active)&&route().page==='payouts')workspace.payoutTimer=setTimeout(refresh,4000);});
}
