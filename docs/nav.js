// Scoresheet: one bottom tab bar on every page, so the three pages feel like one app.
(function(){
  var tabs=[
    {href:"board.html", label:"Tonight", icon:'<ellipse cx="12" cy="9" rx="8" ry="3.5"/><path d="M4 9v5.5c0 1.9 3.6 3.5 8 3.5s8-1.6 8-3.5V9"/>'},
    {href:"sim.html", label:"Sim", icon:'<path d="M4 19V5"/><path d="M4 19h16"/><path d="M7 15l4-4 3 3 5-6"/>'},
    {href:"app.html", label:"Backtest", icon:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.6"/>'}
  ];
  var page=(location.pathname.split("/").pop()||"board.html").toLowerCase();
  if(page==="index.html") page="board.html";
  var nav=document.createElement("nav");
  nav.className="tabbar"; nav.setAttribute("aria-label","Scoresheet");
  tabs.forEach(function(t){
    var a=document.createElement("a");
    a.href=t.href;
    if(t.href===page) a.setAttribute("aria-current","page");
    a.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true">'+t.icon+'</svg><span>'+t.label+'</span>';
    nav.appendChild(a);
  });
  document.body.appendChild(nav);
})();
