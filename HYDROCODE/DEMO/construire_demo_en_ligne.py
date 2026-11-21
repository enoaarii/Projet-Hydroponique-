# -*- coding: utf-8 -*-
# Construit la page de démonstration en ligne : le dashboard de la tour, plus le drapeau
# DEMO_EN_LIGNE et la porte de connexion (identifiant, mot de passe, captcha), qui sur la
# tour est assurée par le serveur (acces.py) et ne peut donc pas exister dans une page seule.
s = open("hydrotour.html", encoding="utf-8", newline="").read()

old = "<title>HydroTour</title>"
assert old in s
s = s.replace(old, """<title>HydroTour - dashboard de démonstration</title>
<!-- Démonstration en ligne : la page est celle de la tour, sans Raspberry derrière. Les mesures
     sont simulées, et les actions qui demandent le matériel le disent. -->
<script>window.DEMO_EN_LIGNE=true;</script>""", 1)

porte = """
<!-- ================= Porte de connexion de la démonstration =================
     Elle reproduit l'écran de connexion de la tour (identifiant, mot de passe, captcha).
     Elle s'exécute dans le navigateur et ne protège rien, puisque le code de la page est
     lisible : la vraie sécurité est celle du serveur (acces.py), décrite en partie 8.6. -->
<div id="porte" role="dialog" aria-modal="true" aria-label="Connexion">
  <form id="porte-f" autocomplete="on">
    <h1>HydroTour</h1>
    <p>Dashboard de démonstration. Identifiant <b>demo</b>, mot de passe <b>hydrotour-demo</b>.</p>
    <label>Identifiant <input id="porte-id" autocomplete="username" autocapitalize="none" required></label>
    <label>Mot de passe <input id="porte-mdp" type="password" autocomplete="current-password" required></label>
    <label>Recopie le code <input id="porte-cap" autocapitalize="characters" autocomplete="off" maxlength="5" required></label>
    <div class="porte-cap"><canvas id="porte-img" width="150" height="50" aria-label="Image du code"></canvas>
      <button type="button" id="porte-autre">Autre image</button></div>
    <button type="submit" id="porte-ok">Se connecter</button>
    <p id="porte-msg" role="status"></p>
  </form>
</div>
<style>
#porte{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;
  background:var(--bg);padding:16px;overflow:auto}
#porte-f{background:var(--surface);border-radius:16px;padding:22px;max-width:360px;width:100%;
  display:grid;gap:10px;box-shadow:0 10px 40px rgba(0,0,0,.18)}
#porte h1{margin:0;font-size:20px}
#porte p{margin:0;color:var(--muted);font-size:13px}
#porte label{display:grid;gap:4px;font-size:13px;color:var(--muted)}
#porte input{font:inherit;padding:9px 10px;border-radius:9px;border:1px solid var(--line);
  background:var(--bg);color:var(--ink)}
#porte .porte-cap{display:flex;align-items:center;gap:10px}
#porte canvas{border-radius:8px;border:1px solid var(--line);background:#fff}
#porte button{font:inherit;padding:9px 14px;border-radius:999px;border:0;cursor:pointer}
#porte-autre{background:var(--bg);color:var(--ink);border:1px solid var(--line)}
#porte-ok{background:var(--accent);color:var(--accent-ink);font-weight:600}
#porte-msg{min-height:1.2em;color:#c0392b}
</style>
<script>
(function(){
  var ID='demo', MDP='hydrotour-demo', code='';
  var LETTRES='ABCDEFGHJKLMNPQRSTUVWXYZ23456789';   // sans I, O, 0 et 1, trop ressemblants
  function dessiner(){
    code=''; for(var i=0;i<5;i++) code+=LETTRES[Math.floor(Math.random()*LETTRES.length)];
    var c=document.getElementById('porte-img'), g=c.getContext('2d');
    g.fillStyle='#fff'; g.fillRect(0,0,c.width,c.height);
    for(var j=0;j<6;j++){                            // quelques traits, pour brouiller l'image
      g.strokeStyle='rgba(0,0,0,.18)'; g.beginPath();
      g.moveTo(Math.random()*c.width,Math.random()*c.height);
      g.lineTo(Math.random()*c.width,Math.random()*c.height); g.stroke();
    }
    for(var k=0;k<code.length;k++){                  // chaque lettre penchée au hasard
      g.save(); g.translate(16+k*26, 32+(Math.random()*8-4));
      g.rotate((Math.random()*0.5-0.25));
      g.font='bold 25px Georgia, serif'; g.fillStyle='#1d1d1f';
      g.fillText(code[k], 0, 0); g.restore();
    }
  }
  // Le dashboard ouvre tout seul sa fenêtre « Quel légume cultives-tu ? ». Une fenêtre de ce
  // type passe au-dessus de tout, y compris de la porte : on la referme tant que la porte est
  // là, et on la rouvre une fois la connexion faite.
  var legume=false, garde=setInterval(function(){
    var d=document.getElementById('setup-dlg');
    if(d&&d.open&&document.getElementById('porte')){ legume=true; d.close(); }
  }, 100);
  function essayer(e){
    e.preventDefault();
    var id=document.getElementById('porte-id').value.trim();
    var mdp=document.getElementById('porte-mdp').value;
    var cap=document.getElementById('porte-cap').value.trim().toUpperCase();
    var msg=document.getElementById('porte-msg');
    if(cap!==code){ msg.textContent='Le code recopié ne correspond pas.'; dessiner();
                    document.getElementById('porte-cap').value=''; return; }
    if(id!==ID||mdp!==MDP){ msg.textContent='Identifiant ou mot de passe incorrect.'; dessiner();
                    document.getElementById('porte-cap').value=''; return; }
    clearInterval(garde);
    document.getElementById('porte').remove();
    window.dispatchEvent(new Event('resize'));       // les graphiques se remettent à la bonne taille
    var d=document.getElementById('setup-dlg');
    if(legume&&d&&!d.open) d.showModal();
  }
  function demarrer(){
    dessiner();
    document.getElementById('porte-autre').addEventListener('click',function(){
      dessiner(); document.getElementById('porte-msg').textContent='';});
    document.getElementById('porte-f').addEventListener('submit',essayer);
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',demarrer);
  else demarrer();
})();
</script>
"""
assert "</body>" in s
s = s.replace("</body>", porte + "</body>", 1)
open("/home/claude/demo_site/index.html", "w", encoding="utf-8", newline="").write(s)
print("ok", len(s))
