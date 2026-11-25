let token=localStorage.getItem("gold_token")||"";
let refreshToken=sessionStorage.getItem("gold_refresh_token")||"";
const api=async(path,opts={})=>{
  const send=(access)=>fetch(path,{...opts,headers:{"Content-Type":"application/json",...(access?{Authorization:"Bearer "+access}:{}),...(opts.headers||{})}});
  let response=await send(token);
  if(response.status===401&&refreshToken&&!path.endsWith("/auth/refresh")&&!path.endsWith("/auth/logout")){
    try{const refreshed=await fetch("/api/auth/refresh",{method:"POST",headers:{Authorization:"Bearer "+refreshToken,"Content-Type":"application/json"},body:"{}"});
      if(refreshed.ok){const data=await refreshed.json();token=data.access_token;localStorage.setItem("gold_token",token);response=await send(token)}
      else{refreshToken="";sessionStorage.removeItem("gold_refresh_token")}
    }catch{}
  }
  return response;
};
async function check(){try{let r=await fetch("/api/health/live");document.getElementById("apiState").textContent=r.ok?"API online":"API issue"}catch{document.getElementById("apiState").textContent="API offline"}}
async function auth(kind){let d={email:email.value,password:password.value};let r=await api("/api/auth/"+kind,{method:"POST",body:JSON.stringify(d)});let j=await r.json();authMsg.textContent=j.error||j.message||(j.access_token?"Signed in":"Check your email for the verification code.");if(r.ok&&j.access_token){token=j.access_token;localStorage.setItem("gold_token",token);refreshToken=j.refresh_token||refreshToken;if(refreshToken)sessionStorage.setItem("gold_refresh_token",refreshToken);loadAccounts();loadLicence();loadSubscriptionStatus();checkAdmin()}}
async function addAccount(){let d={label:label.value,login:login.value,server:server.value,mt5_password:mt5Password.value,symbol:symbol.value||"AUTO",mode:"demo"};let r=await api("/api/accounts",{method:"POST",body:JSON.stringify(d)});let j=await r.json();if(r.ok){mt5Password.value="";alert("Demo account registered. Copy the EA token into the EA input now; it is shown only once.");prompt("EA account token — copy this into InpAccountToken",j.ea_token)}else{alert(j.error)}loadAccounts()}
async function loadAccounts(){let r=await api("/api/accounts");let j=await r.json();let box=document.getElementById("accounts");if(!r.ok){box.innerHTML="<p class='muted'>Sign in first.</p>";return}box.innerHTML=(j.accounts||[]).map(a=>`<article class="account"><h3>${escapeHtml(a.label)} · ${escapeHtml(a.mode)}${a.is_deleted?" · REMOVING":""}</h3><p>API account ID: ${a.id}</p><p>MT5 ${escapeHtml(a.login)} · ${escapeHtml(a.server)} · ${escapeHtml(a.symbol)}</p><p>Desired: ${a.desired_state} | Actual: ${a.actual_state} · ${a.telemetry?.connected_to_broker?"Broker connected":"Broker disconnected"}</p><p>Balance: ${a.telemetry?.balance??'—'} · Equity: ${a.telemetry?.equity??'—'} · Floating P/L: ${a.telemetry?.floating_pnl??'—'} · Positions: ${a.telemetry?.open_positions_count??'—'}</p>${a.is_deleted?`<p class="muted">New entries are disabled. The assigned EA remains active to manage existing positions until the account is flat and connected.</p><button class="secondary" onclick="command(${a.id},'CLOSE_ALL')">Close all positions</button>`:`<button onclick="command(${a.id},'START')">Start</button><button class="secondary" onclick="command(${a.id},'STOP')">Stop entries</button><button class="secondary" onclick="command(${a.id},'CLOSE_ALL')">Close all & stop</button><button class="secondary" onclick="command(${a.id},'EMERGENCY_STOP')">Emergency stop</button><button class="secondary" onclick="editRisk(${a.id})">Risk settings</button><button class="secondary" onclick="updateCredential(${a.id})">Update MT5 password</button><button class="secondary" onclick="regenerateToken(${a.id})">Regenerate EA token</button><button class="secondary" onclick="removeAccount(${a.id})">Remove account</button>`}</article>`).join("")||"<p>No accounts registered.</p>"}
async function removeAccount(id){if(!confirm("Remove this MT5 account? New entries will stop. If positions are open, the assigned EA will keep managing them until the account is flat and connected."))return;const r=await api(`/api/accounts/${id}`,{method:"DELETE"});const j=await r.json();alert(r.ok?(j.removal_pending?"Removal pending: the EA will keep managing existing positions until flat.":"Account removed from your active account list."):(j.error||"Failed"));loadAccounts()}

async function command(id,name){if(name==="CLOSE_ALL"&&!confirm("Close all positions on this account?"))return;let r=await api(`/api/accounts/${id}/commands`,{method:"POST",body:JSON.stringify({command:name})});let j=await r.json();alert(r.ok?`${name} queued`:j.error);loadAccounts()}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
async function plans(){let r=await fetch("/api/plans");let j=await r.json();document.getElementById("plans").innerHTML=j.plans.map(p=>`<div class="plan"><b>$${p.amount} USD</b><p>${p.duration_days} days</p><button onclick="buy('${p.code}')">Subscribe</button></div>`).join("")}
async function buy(code){let r=await api("/api/payments/flutterwave/initialize",{method:"POST",body:JSON.stringify({plan_code:code,currency:"USD"})});let j=await r.json();if(r.ok)location.href=j.checkout_url;else alert(j.error)}
check();plans();if(token){loadAccounts();loadLicence();loadSubscriptionStatus();checkAdmin()}setInterval(()=>{if(token){loadAccounts();loadLicence();loadSubscriptionStatus()}},15000)

async function activateLicence(){
  const code=document.getElementById("licenseCode").value.trim();
  if(!code){document.getElementById("licenceState").textContent="Enter a licence code.";return}
  const r=await api("/api/licences/activate",{method:"POST",body:JSON.stringify({code})});
  const j=await r.json();
  document.getElementById("licenceState").textContent=r.ok?`Licence active: ${j.code||code}${j.expires_at?" · expires "+j.expires_at:""}`:(j.error||"Activation failed");
}
async function loadLicence(){
  const r=await api("/api/licences/status"); const j=await r.json();
  document.getElementById("licenceState").textContent=r.ok?(j.active?`Active: ${j.code}${j.expires_at?" · expires "+j.expires_at:""}`:`No active licence · trial uses ${j.trial_uses||0}/2`):(j.error||"Sign in first.");
}
async function loadSubscriptionStatus(){const r=await api("/api/subscriptions/status");const j=await r.json();const box=document.getElementById("subscriptionState");if(box)box.textContent=r.ok?(j.active?`${j.subscription.plan_code} · expires ${j.subscription.expires_at} · ${j.subscription.days_remaining} days left`:"No paid subscription active"):(j.error||"Sign in first.");}


async function regenerateToken(id){
  if(!confirm("Regenerating invalidates the current EA token. Continue?"))return;
  const r=await api(`/api/accounts/${id}/ea-token/regenerate`,{method:"POST",body:"{}"});
  const j=await r.json();
  if(r.ok)prompt("New EA token — update InpAccountToken in MT5",j.ea_token);
  else alert(j.error||"Could not regenerate token");
}

async function verifyEmail(){let r=await api("/api/auth/verify-email",{method:"POST",body:JSON.stringify({email:email.value,code:verifyCode.value.trim()})});let j=await r.json();authMsg.textContent=j.error||"Email verified.";if(r.ok&&j.access_token){token=j.access_token;localStorage.setItem("gold_token",token);refreshToken=j.refresh_token||refreshToken;if(refreshToken)sessionStorage.setItem("gold_refresh_token",refreshToken);loadAccounts();loadLicence();loadSubscriptionStatus();checkAdmin()}}
async function resendVerification(){let r=await api("/api/auth/verification/resend",{method:"POST",body:JSON.stringify({email:email.value})});let j=await r.json();authMsg.textContent=j.error||j.message}
async function requestPasswordReset(){let r=await api("/api/auth/password-reset/request",{method:"POST",body:JSON.stringify({email:email.value})});let j=await r.json();authMsg.textContent=j.message||j.error}
async function confirmPasswordReset(){let r=await api("/api/auth/password-reset/confirm",{method:"POST",body:JSON.stringify({email:email.value,code:resetCode.value.trim(),new_password:newPassword.value})});let j=await r.json();authMsg.textContent=j.message||j.error}
async function loadPaymentsHistory(){let r=await api("/api/dashboard/payments");let j=await r.json();let box=document.getElementById("paymentHistory");box.textContent=r.ok?JSON.stringify(j,null,2):(j.error||"Sign in to view payment history.")}

async function logout(){try{let r=await api("/api/auth/logout",{method:"POST",body:JSON.stringify({refresh_token:refreshToken})});if(!r.ok&&refreshToken)await fetch("/api/auth/logout-refresh",{method:"POST",headers:{Authorization:"Bearer "+refreshToken,"Content-Type":"application/json"},body:"{}"})}catch{}token="";refreshToken="";localStorage.removeItem("gold_token");sessionStorage.removeItem("gold_refresh_token");document.getElementById("accounts").innerHTML="<p class=\"muted\">Signed out.</p>";document.getElementById("adminPanel").hidden=true}
async function loadTradeHistory(){let r=await api("/api/dashboard/trades");let j=await r.json();let box=document.getElementById("paymentHistory");box.textContent=r.ok?JSON.stringify(j,null,2):(j.error||"Sign in to view trades.")}
async function editRisk(id){let r0=await api("/api/accounts");let j0=await r0.json();let a=(j0.accounts||[]).find(x=>x.id===id);let defaults={basket_profit_target_usd:5,basket_loss_limit_usd:20,max_drawdown_percent:35,max_positions:0,one_entry_per_m1_bar:false};let initial=Object.assign(defaults,a?.risk_settings||{});let raw=prompt("Enter account risk settings as JSON. Values are validated by the server.",JSON.stringify(initial));if(raw===null)return;let payload;try{payload=JSON.parse(raw)}catch{alert("Invalid JSON");return}let r=await api(`/api/accounts/${id}/commands`,{method:"POST",body:JSON.stringify({command:"SETTINGS",payload})});let j=await r.json();alert(r.ok?"Risk settings command queued.":(j.error||"Failed"));loadAccounts()}
async function updateCredential(id){let pass=prompt("Enter the new MT5 trading password. It will be encrypted by the API.");if(pass===null)return;let r=await api(`/api/accounts/${id}/credentials`,{method:"PUT",body:JSON.stringify({mt5_password:pass})});let j=await r.json();alert(r.ok?"Credential updated. New entries are stopped until you start the account again.":(j.error||"Failed"));loadAccounts()}
