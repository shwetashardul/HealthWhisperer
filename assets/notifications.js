// Web Notifications helper; exposes globals for Streamlit to call via injected JS
(function(){
  function permissionStatus(){
    if (!('Notification' in window)) return 'unsupported';
    return Notification.permission; // 'granted' | 'denied' | 'default'
  }

  async function requestPermission(){
    if (!('Notification' in window)) return 'unsupported';
    try{ const r = await Notification.requestPermission(); return r; }catch(e){ return permissionStatus(); }
  }

  function notify(title, body){
    if (!('Notification' in window)) return 'unsupported';
    if (Notification.permission !== 'granted') return 'blocked';
    try {
      const n = new Notification(title || 'Health Whisperer', { body: body || '' , tag: 'health-whisperer' });
      try{ n.onclick = () => { try{ window.focus(); }catch(e){} }; }catch(e){}
      return 'shown';
    } catch(e){ return 'blocked'; }
  }

  function isInIframe(){
    try { return window.top !== window.self; } catch(e){ return true; }
  }

  window.hwPermissionStatus = permissionStatus;
  window.hwRequestPermission = requestPermission;
  window.hwNotify = notify;
  window.hwIsInIframe = isInIframe;
})();


