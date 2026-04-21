// auth.js - Simple LoginActivity and RegisterActivity
(function(){
  const api = {
    login: '/auth/login',
    signup: '/auth/signup'
  };

  function showStatus(el, msg, isError){
    el.innerHTML = isError ? `<div class="error-text">${msg}</div>` : `${msg}`;
  }

  async function postJSON(url, body){
    const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const data = await res.json().catch(()=> ({}));
    return {ok: res.ok, status: res.status, data};
  }

  // Auto-redirect if already logged in
  function checkAutoLogin(){
    try{
      const t = localStorage.getItem('access_token');
      // Only redirect to '/' if we have a token and we're NOT already on the root page.
      // This avoids a reload loop when auth.js is loaded on the root page.
      if (t) {
        const path = (window.location && window.location.pathname) ? window.location.pathname : '/';
        // Do not redirect if we're already at '/', or already on any /auth path (login/register/logout pages).
        if (path !== '/' && !path.startsWith('/auth')) {
          try{ console.debug('[auth.js] checkAutoLogin: redirecting to /', new Error().stack); }catch(e){}
          window.location.href = '/';
        }
      }
    } catch(e) {}
  }
  function initLogin(){
    checkAutoLogin();
    const form = document.getElementById('loginForm');
    if(!form) return;
    const status = document.getElementById('status');
    const toggle = document.getElementById('togglePass');
    toggle && toggle.addEventListener('click', ()=>{
      const pwd = document.getElementById('password');
      if(!pwd) return; pwd.type = pwd.type==='password' ? 'text' : 'password'; toggle.textContent = pwd.type==='password' ? 'Show' : 'Hide';
    });

    form.addEventListener('submit', async (e)=>{
      e.preventDefault();
      const email = (document.getElementById('email')||{}).value||'';
      const password = (document.getElementById('password')||{}).value||'';
      if(!email || !password){ showStatus(status, 'Please enter both email and password', true); return; }
      const submit = document.getElementById('submitBtn');
      submit && (submit.disabled = true, submit.textContent = 'Signing in...');
      const res = await postJSON(api.login, {email, password});
      if(res.ok){
        try{ localStorage.setItem('access_token', res.data.access_token); localStorage.setItem('refresh_token', res.data.refresh_token); localStorage.setItem('user', JSON.stringify(res.data.user||{})); }catch(e){}
  showStatus(status, 'Login successful — redirecting...');
  setTimeout(()=>{ try{ console.debug('[auth.js] login submit: redirecting to /', new Error().stack); }catch(e){} window.location.href = '/'; }, 600);
      } else {
        showStatus(status, res.data.detail || res.data.message || 'Invalid credentials', true);
      }
      submit && (submit.disabled = false, submit.textContent = 'Sign in');
    });
  }

  function initRegister(){
    checkAutoLogin();
    const form = document.getElementById('registerForm');
    if(!form) return;
    const status = document.getElementById('status');
    const toggle = document.getElementById('togglePassReg');
    toggle && toggle.addEventListener('click', ()=>{
      const pwd = document.getElementById('password');
      if(!pwd) return; pwd.type = pwd.type==='password' ? 'text' : 'password'; toggle.textContent = pwd.type==='password' ? 'Show' : 'Hide';
    });

    form.addEventListener('submit', async (e)=>{
      e.preventDefault();
      const first_name = (document.getElementById('first_name')||{}).value||'';
      const last_name = (document.getElementById('last_name')||{}).value||'';
      const email = (document.getElementById('email')||{}).value||'';
      const password = (document.getElementById('password')||{}).value||'';
      if(!email || !password){ showStatus(status, 'Email and password are required', true); return; }
      if(password.length < 8){ showStatus(status, 'Password must be at least 8 characters', true); return; }
      const submit = document.getElementById('submitBtn');
      submit && (submit.disabled = true, submit.textContent = 'Creating...');
      const res = await postJSON(api.signup, {first_name, last_name, email, password});
      if(res.ok){ showStatus(status, 'Account created — redirecting to sign in...'); setTimeout(()=> window.location.href = '/auth/login', 900); }
      else { showStatus(status, res.data.detail || res.data.message || 'Registration failed', true); }
      submit && (submit.disabled = false, submit.textContent = 'Create account');
    });
  }

  // Auto-init based on present forms
  document.addEventListener('DOMContentLoaded', ()=>{
    initLogin(); initRegister();
    // Initialize header auth button state and logout if present
    try{
      const headerBtn = document.getElementById('loginBtn');
      const authMenu = document.getElementById('authMenu');
      const logoutBtn = document.getElementById('logoutBtn');
      const profileLink = document.getElementById('profileLink');

      // Centralized logout helper used by multiple buttons
      async function doLogout(triggerButton){
        // Centralized logout helper. Returns a Promise that resolves with an object { ok, status, data }
        let respInfo = { ok: false, status: 0, data: null };
        try{
          const token = localStorage.getItem('access_token');
          if(triggerButton) triggerButton.disabled = true;
          console.log('Logging out, sending request to /auth/logout', { tokenPresent: !!token });

          // Use keepalive so browser attempts to complete the request even during navigation/unload.
          const res = await fetch('/auth/logout', {
            method: 'POST',
            keepalive: true,
            headers: Object.assign({'Content-Type':'application/json'}, token ? {'Authorization': 'Bearer ' + token} : {}),
            body: JSON.stringify({ token })
          });

          respInfo.status = res.status;
          respInfo.ok = res.ok;
          try{
            respInfo.data = await res.json();
          }catch(jsonErr){
            console.warn('Failed to parse logout response JSON', jsonErr);
            respInfo.data = null;
          }

          console.log('Logout response', respInfo);

          if(!res.ok){
            // Surface a clear message for debugging and keep logs in console
            console.warn('Logout returned non-OK status', res.status, respInfo.data);
            try{ alert('Logout failed: ' + (respInfo.data && (respInfo.data.message || respInfo.data.detail) ? (respInfo.data.message || respInfo.data.detail) : ('HTTP ' + res.status))); }catch(e){}
          }

        }catch(err){
          console.error('Logout helper error', err);
          // If fetch failed (possibly due to navigation), try sendBeacon as a best-effort fallback.
          try{
            if(navigator && typeof navigator.sendBeacon === 'function'){
              console.log('Attempting navigator.sendBeacon fallback for /auth/logout');
              const payload = JSON.stringify({ token });
              const ok = navigator.sendBeacon('/auth/logout', new Blob([payload], {type: 'application/json'}));
              console.log('sendBeacon result', ok);
            }
          }catch(beErr){
            console.warn('sendBeacon fallback failed', beErr);
          }
        }finally{
          // Always remove sensitive tokens locally. If you want to preserve tokens when logout fails,
          // adjust this behavior (we clear to avoid leaving stale tokens in the client).
          try{ localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token'); localStorage.removeItem('user'); }catch(e){}
          // ensure redirect even if request failed - allow a short delay so logs/alerts are visible
          setTimeout(()=>{ try{ console.debug('[auth.js] doLogout finally: redirecting to /', new Error().stack); }catch(e){} try{ window.location.href = '/'; }catch(e){} }, 120);
        }
        return respInfo;
      }
      // expose for debugging in console
      try{ window.doLogout = doLogout; }catch(e){}

      if(headerBtn){
        const token = localStorage.getItem('access_token');
        const userRaw = localStorage.getItem('user');
        let displayName = null;
        if(userRaw){ try{ const u = JSON.parse(userRaw); displayName = (u.first_name || u.email || u.id || null); }catch(e){} }
        if(token){
          // Show account name and enable dropdown
          headerBtn.querySelector('span') && (headerBtn.querySelector('span').textContent = displayName || 'Account');
          headerBtn.setAttribute('href', '#');
          headerBtn.classList.add('has-account');

          // ensure there's a logout button in the dropdown and a visible inline logout next to the pill
          try{
            const wrapper = headerBtn.parentElement || headerBtn.parentNode;

            // 1) Ensure a logout item exists inside the auth menu (so menu always shows it)
            try{
              let menuLogout = document.getElementById('logoutMenuBtn');
              if(!menuLogout && authMenu && authMenu instanceof HTMLElement){
                menuLogout = document.createElement('button');
                menuLogout.id = 'logoutMenuBtn';
                menuLogout.className = 'auth-menu-item logout-button';
                menuLogout.textContent = 'Logout';
                authMenu.appendChild(menuLogout);
              }
              if(menuLogout){
                menuLogout.addEventListener('click', async function(e){ e.preventDefault(); await doLogout(menuLogout); });
              }
            }catch(e){}

            // 2) Create a visible inline logout button next to the account pill (so user sees logout immediately)
            try{
              let visibleInline = document.getElementById('logoutInlineBtn');
              if(!visibleInline && wrapper){
                visibleInline = document.createElement('button');
                visibleInline.id = 'logoutInlineBtn';
                visibleInline.className = 'logout-inline-visible';
                visibleInline.textContent = 'Logout';
                // Insert after the headerBtn for predictable layout
                if(headerBtn.nextSibling) wrapper.insertBefore(visibleInline, headerBtn.nextSibling);
                else wrapper.appendChild(visibleInline);
              }
              if(visibleInline){
                visibleInline.addEventListener('click', async function(e){ e.preventDefault(); await doLogout(visibleInline); });
              }
            }catch(e){}

          }catch(err){}

          // Toggle menu
          headerBtn.addEventListener('click', function(e){
            e.preventDefault();
            if(!authMenu) return;
            authMenu.style.display = authMenu.style.display === 'block' ? 'none' : 'block';
          });

          // Wire logout button
          if(logoutBtn){
            logoutBtn.addEventListener('click', async function(e){ e.preventDefault(); await doLogout(logoutBtn); });
          }

          // Profile link should open /profile
          if(profileLink) profileLink.setAttribute('href','/profile');

          // close menu if clicked outside
          document.addEventListener('click', function(ev){ if(!authMenu) return; const within = ev.target.closest && (ev.target.closest('.auth-dropdown')); if(!within) authMenu.style.display = 'none'; });
        } else {
          // not logged in: ensure it links to login and hide menu
          headerBtn.setAttribute('href','/auth/login');
          if(authMenu) authMenu.style.display = 'none';
        }
      }
    }catch(e){}
  });

})();
