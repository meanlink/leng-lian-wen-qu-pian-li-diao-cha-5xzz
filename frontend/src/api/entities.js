import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const payouts={
 batches:()=>api('/batches'),createBatch:data=>api('/batches',{method:'POST',body:JSON.stringify(data)}),events:id=>api('/batches/'+id+'/events'),
 list:()=>api('/payout-orders'),get:id=>api('/payout-orders/'+id),create:data=>api('/payout-orders',{method:'POST',body:JSON.stringify(data)}),
 confirm:id=>api('/payout-orders/'+id+'/confirm',{method:'POST'}),cancel:id=>api('/payout-orders/'+id+'/cancel',{method:'POST'}),
 retry:id=>api('/payout-orders/'+id+'/retry',{method:'POST'}),reconcile:id=>api('/payout-orders/'+id+'/reconcile',{method:'POST'})};
export const paygate={state:()=>api('/paygate/state'),faults:data=>api('/paygate/faults',{method:'PUT',body:JSON.stringify(data)})};
