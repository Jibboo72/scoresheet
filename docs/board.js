(function(){
  var DATA=null, market="goal", game="all";
  var BEST=0.05, FLAG=0.30;
  var $=function(id){return document.getElementById(id)};
  var pct=function(v){return (v*100).toFixed(0)+"%"};
  var am=function(p){return p==null?"—":(p>0?"+"+p:""+p)};
  var ev=function(v){return (v>0?"+":"")+(v*100).toFixed(0)+"%"};
  var esc=function(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})};

  function rows(){
    return DATA.players.filter(function(p){return game==="all"||String(p.game_id)===game})
      .map(function(p){return {p:p, m:p[market]}});
  }
  function playItem(r){
    var li=document.createElement("li"); li.className="play";
    li.innerHTML="<span class='who'>"+esc(r.p.name)+"</span>"+
      "<span class='game'>"+r.p.team+" vs "+r.p.opp+"</span>"+
      "<span class='nums'>Model <b>"+pct(r.m.p)+"</b>, fair "+am(r.m.fair)+", best <b>"+am(r.m.price)+"</b> "+esc(r.m.book)+"</span>"+
      "<span class='ev'><b>"+ev(r.m.ev)+"</b><span>EV</span></span>";
    return li;
  }
  function render(){
    document.querySelectorAll(".switch button").forEach(function(b){
      b.setAttribute("aria-pressed", b.dataset.market===market?"true":"false");
    });
    var chips=$("games"); chips.innerHTML="";
    [{id:"all",label:"All games"}].concat(DATA.games.map(function(g){return {id:String(g.id),label:g.away+" @ "+g.home}}))
      .forEach(function(g){
        var b=document.createElement("button"); b.textContent=g.label;
        b.setAttribute("aria-pressed", g.id===game?"true":"false");
        b.onclick=function(){game=g.id; render();};
        chips.appendChild(b);
      });
    $("status").textContent=DATA.odds_status;

    var rs=rows(), priced=rs.filter(function(r){return r.m.ev!=null});
    var best=priced.filter(function(r){return r.m.ev>=BEST&&r.m.ev<FLAG}).sort(function(a,b){return b.m.ev-a.m.ev});
    var flags=priced.filter(function(r){return r.m.ev>=FLAG}).sort(function(a,b){return b.m.ev-a.m.ev});
    var ol=$("best"); ol.innerHTML=""; best.forEach(function(r){ol.appendChild(playItem(r))});
    $("bestNote").textContent = !priced.length
      ? "No sportsbook prices yet. Use the Fair column below and compare it to your book."
      : best.length ? "Model edge of 5% or more against the best available price."
      : "Nothing clears a 5% edge right now. Passing is a fine bet.";
    var fl=$("flags"); fl.innerHTML=""; fl.className="plays flagged";
    flags.forEach(function(r){fl.appendChild(playItem(r))});
    $("flagBlock").hidden=!flags.length;

    var tb=$("all"); tb.innerHTML="";
    rs.sort(function(a,b){return b.m.p-a.m.p}).forEach(function(r){
      var tr=document.createElement("tr");
      tr.innerHTML="<td>"+esc(r.p.name)+"<span class='sub'>"+r.p.team+" vs "+r.p.opp+"</span></td>"+
        "<td>"+pct(r.m.p)+"</td><td>"+am(r.m.fair)+"</td><td>"+am(r.m.price)+"</td>"+
        "<td class='"+(r.m.ev>=BEST?"pos":"")+"'>"+(r.m.ev==null?"—":ev(r.m.ev))+"</td>";
      tb.appendChild(tr);
    });
  }
  document.querySelectorAll(".switch button").forEach(function(b){
    b.onclick=function(){market=b.dataset.market; render();};
  });
  fetch("data/board.json",{cache:"no-store"})
    .then(function(r){if(!r.ok) throw 0; return r.json();})
    .then(function(d){
      DATA=d;
      var day=new Date(d.date+"T12:00:00");
      $("when").textContent=day.toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"});
      if(!d.games.length){
        $("emptyTitle").textContent="No games today"; $("emptyText").textContent="The next board appears on the next game day.";
        $("empty").hidden=false; return;
      }
      $("app").hidden=false; render();
    })
    .catch(function(){ $("empty").hidden=false; });
})();
