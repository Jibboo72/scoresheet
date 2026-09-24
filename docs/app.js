(function(){
  var DATA=null, market="sog", line="2.5", selected=null;
  var $=function(id){return document.getElementById(id)};
  var pct=function(v,d){return v==null?"—":(v*100).toFixed(d==null?1:d)+"%"};
  var signed=function(v){return v==null?"—":(v>0?"+":"")+(v*100).toFixed(1)+"%"};
  var fmt=function(n){return n==null?"—":n.toLocaleString()};
  function current(){
    var m=DATA.markets[market];
    return market==="sog"?m.lines[line]:m;
  }
  function label(){
    if(market==="sog") return "Shots over "+line;
    return DATA.markets[market].label;
  }
  function render(){
    document.querySelectorAll(".switch button").forEach(function(b){
      b.setAttribute("aria-pressed", b.dataset.market===market?"true":"false");
    });
    var lines=$("lines"); lines.innerHTML="";
    if(market==="sog"){
      Object.keys(DATA.markets.sog.lines).forEach(function(l){
        var b=document.createElement("button");
        b.textContent="Over "+l; b.setAttribute("aria-pressed", l===line?"true":"false");
        b.onclick=function(){line=l; selected=null; render();};
        lines.appendChild(b);
      });
    }
    var s=current();
    var sk=$("skill");
    sk.textContent=signed(s.skill);
    sk.className="num "+(s.skill>=0?"up":"down");
    $("verdictText").textContent = label()+": "+(s.skill>=0
      ? "sharper than a plain season average."
      : "worse than a plain season average. Needs work before betting.");
    $("fN").textContent=fmt(s.n);
    $("fBase").textContent=pct(s.base_rate);
    $("fEce").textContent=(s.ece*100).toFixed(1)+" pts";
    $("fEarly").textContent=signed(s.early_skill);
    $("c60").textContent=s.confident.n? pct(s.confident.hit): "—";
    $("c60s").textContent=s.confident.n
      ? "hit rate when it said 60%+ ("+fmt(s.confident.n)+" bets, expected "+pct(s.confident.pred)+")"
      : "never said 60%+ on this market";
    $("ctop").textContent=pct(s.top5.hit);
    $("ctops").textContent="hit rate on its top 5% ("+fmt(s.top5.n)+" bets, expected "+pct(s.top5.pred)+")";
    var tb=$("rows"); tb.innerHTML="";
    s.calibration.forEach(function(c){
      var gap=c.actual-c.pred;
      var tr=document.createElement("tr");
      tr.innerHTML="<td>"+Math.round(c.lo*100)+"–"+Math.round(c.hi*100)+"%</td><td>"+pct(c.actual)+
        "</td><td class='"+(Math.abs(gap)>0.03&&c.n>=100?"gap-bad":"")+"'>"+(gap>0?"+":"")+(gap*100).toFixed(1)+
        "</td><td>"+fmt(c.n)+"</td>";
      tb.appendChild(tr);
    });
    var fb=$("fitBlock");
    if(market==="sog"){
      fb.hidden=false;
      var ul=$("fits"); ul.innerHTML="";
      DATA.markets.sog.fits.forEach(function(f){
        var li=document.createElement("li");
        if(f.name===DATA.markets.sog.chosen) li.className="best";
        li.innerHTML="<span>"+f.name+(f.name===DATA.markets.sog.chosen?"<em>Used</em>":"")+"</span><span>"+f.loglik.toFixed(4)+"</span>";
        ul.appendChild(li);
      });
    } else fb.hidden=true;
    drawChart(s);
  }
  function drawChart(s){
    var svg=$("chart"), W=320, H=300, L=48, R=12, T=10, B=40;
    var pts=s.calibration.filter(function(c){return c.n>=20});
    var hi=Math.max(0.3, Math.ceil(Math.max.apply(null, pts.map(function(c){return Math.max(c.pred,c.actual)}).concat([0.1]))*10)/10);
    var x=function(v){return L+(W-L-R)*v/hi}, y=function(v){return H-B-(H-T-B)*v/hi};
    var maxN=Math.max.apply(null, pts.map(function(c){return c.n}));
    var g=[];
    for(var t=0;t<=hi+1e-9;t+=hi<=0.5?0.1:0.2){
      g.push("<line class='grid' x1='"+x(0)+"' x2='"+x(hi)+"' y1='"+y(t)+"' y2='"+y(t)+"'/>");
      g.push("<text class='axis' x='"+(L-6)+"' y='"+(y(t)+4)+"' text-anchor='end'>"+Math.round(t*100)+"%</text>");
      g.push("<text class='axis' x='"+x(t)+"' y='"+(H-B+18)+"' text-anchor='middle'>"+Math.round(t*100)+"%</text>");
    }
    g.push("<text class='axis' x='"+(L+(W-L-R)/2)+"' y='"+(H-4)+"' text-anchor='middle'>Model said</text>");
    g.push("<text class='axis' transform='translate(9,"+(T+(H-T-B)/2)+") rotate(-90)' text-anchor='middle'>Actually hit</text>");
    g.push("<line class='perfect' x1='"+x(0)+"' y1='"+y(0)+"' x2='"+x(hi)+"' y2='"+y(hi)+"'/>");
    pts.forEach(function(c,i){
      var r=4+10*Math.sqrt(c.n/maxN);
      g.push("<circle class='dot"+(selected===i?" on":"")+"' data-i='"+i+"' cx='"+x(c.pred)+"' cy='"+y(c.actual)+"' r='"+r.toFixed(1)+"' tabindex='0' role='button' aria-label='Model said "+pct(c.pred)+", hit "+pct(c.actual)+"'/>");
    });
    svg.innerHTML=g.join("");
    svg.querySelectorAll(".dot").forEach(function(el){
      var pick=function(){
        selected=+el.dataset.i; var c=pts[selected];
        $("readout").innerHTML="Model said <strong>"+pct(c.pred)+"</strong>, it hit <strong>"+pct(c.actual)+"</strong> across "+fmt(c.n)+" bets.";
        svg.querySelectorAll(".dot").forEach(function(d){d.classList.toggle("on", +d.dataset.i===selected)});
      };
      el.addEventListener("click",pick);
      el.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();pick();}});
    });
    if(selected==null) $("readout").textContent="Tap a dot for its numbers.";
  }
  document.querySelectorAll(".switch button").forEach(function(b){
    b.onclick=function(){market=b.dataset.market; selected=null; render();};
  });
  fetch("data/backtest.json",{cache:"no-store"})
    .then(function(r){if(!r.ok) throw 0; return r.json();})
    .then(function(d){
      DATA=d;
      var when=new Date(d.generated);
      $("meta").innerHTML="Backtest of "+d.season_tested+"<br>"+d.counts.players.toLocaleString()+" skaters";
      $("foot").textContent="Data from the NHL’s public stats feed. Updated "+when.toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"})+".";
      $("app").hidden=false; render();
    })
    .catch(function(){ $("empty").hidden=false; });
})();
