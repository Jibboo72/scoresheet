(function(){
  var $=function(id){return document.getElementById(id)};
  var pct=function(v){return v==null||isNaN(v)?"—":(v*100).toFixed(0)+"%"};
  var am=function(p){return p==null?"—":(p>0?"+"+p:""+p)};
  var u=function(v){return (v>0?"+":"")+v.toFixed(2)};
  var esc=function(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})};
  var label={goal:"Anytime goal",assist:"1+ assist"};

  function sum(a,f){return a.reduce(function(t,x){return t+f(x)},0)}
  function group(name, picks){
    var g=picks.filter(function(b){return b.status==="win"||b.status==="loss"});
    var priced=g.filter(function(b){return b.units!=null});
    return {name:name, n:g.length, exp:sum(g,function(b){return b.p}), hits:sum(g,function(b){return b.status==="win"?1:0}),
            units:sum(priced,function(b){return b.units}), bets:priced.length};
  }
  function row(cells){var tr=document.createElement("tr"); tr.innerHTML=cells.map(function(c){return "<td>"+c+"</td>"}).join(""); return tr}

  function render(log){
    var graded=log.filter(function(b){return b.status==="win"||b.status==="loss"});
    var bets=graded.filter(function(b){return b.units!=null});
    var units=sum(bets,function(b){return b.units});
    var wins=sum(graded,function(b){return b.status==="win"?1:0});
    var el=$("units"); el.textContent=u(units)+"u"; el.className="num "+(units>=0?"up":"down");
    $("unitsText").textContent = bets.length
      ? "Paper profit on "+bets.length+" priced bets at 1 unit each."
      : "No priced bets graded yet. Add the odds key to track profit.";
    $("fRec").textContent=wins+"-"+(graded.length-wins);
    $("fRoi").textContent=bets.length?(units/bets.length>0?"+":"")+(units/bets.length*100).toFixed(1)+"%":"—";
    $("fHit").textContent=pct(graded.length?wins/graded.length:null);
    $("fExp").textContent=pct(graded.length?sum(graded,function(b){return b.p})/graded.length:null);

    var tb=$("splits"); tb.innerHTML="";
    [group("All picks",log), group(label.goal,log.filter(function(b){return b.market==="goal"})),
     group(label.assist,log.filter(function(b){return b.market==="assist"})),
     group("Edge 5–30%",log.filter(function(b){return b.kind==="bet"&&!b.flag})),
     group("Edge 30%+",log.filter(function(b){return b.flag})),
     group("Top picks, no price",log.filter(function(b){return b.kind==="watch"}))]
     .filter(function(g){return g.n}).forEach(function(g){
       tb.appendChild(row([g.name, g.n, g.exp.toFixed(1), g.hits, g.bets?u(g.units):"—"]));
     });

    var all=group("",log), roi=bets.length?units/bets.length:0;
    var checks=[
      [bets.length>=150, "150+ graded priced bets", bets.length+" so far"],
      [roi>0, "Positive return per bet", bets.length?(roi*100).toFixed(1)+"%":"no priced bets yet"],
      [all.n>=50 && Math.abs(all.hits-all.exp)<=Math.max(3,0.1*all.exp), "Hits within 10% of what the model expected",
        all.n?all.hits+" actual vs "+all.exp.toFixed(1)+" expected":"nothing graded yet"]
    ];
    var ck=$("checks"); ck.innerHTML="";
    checks.forEach(function(c){
      var li=document.createElement("li"); li.className="play";
      li.innerHTML="<span class='who'>"+c[1]+"</span><span class='game'>"+c[2]+"</span><span class='ev'><b style='color:var("+(c[0]?"--blue":"--muted")+")'>"+(c[0]?"Yes":"Not yet")+"</b></span>";
      ck.appendChild(li);
    });

    var pend=log.filter(function(b){return b.status==="pending"});
    var pl=$("pending"); pl.innerHTML="";
    pend.forEach(function(b){
      var li=document.createElement("li"); li.className="play";
      li.innerHTML="<span class='who'>"+esc(b.name)+"</span><span class='game'>"+b.team+" vs "+b.opp+", "+label[b.market]+"</span>"+
        "<span class='nums'>Model <b>"+pct(b.p)+"</b>"+(b.price!=null?", logged at <b>"+am(b.price)+"</b> "+esc(b.book||""):", fair "+am(b.fair))+"</span>"+
        "<span class='ev'><b>"+(b.ev!=null?(b.ev>0?"+":"")+(b.ev*100).toFixed(0)+"%":"Watch")+"</b><span>"+(b.ev!=null?"EV":"")+"</span></span>";
      pl.appendChild(li);
    });
    $("pendingNote").textContent=pend.length?"":"Nothing pending right now.";

    var hist=$("history"); hist.innerHTML="";
    log.filter(function(b){return b.status!=="pending"}).slice().reverse().forEach(function(b){
      var res=b.status==="win"?"<span style='color:var(--blue);font-weight:600'>Win"+(b.units!=null?" "+u(b.units):"")+"</span>"
        :b.status==="loss"?"<span style='color:var(--goal)'>Loss</span>":"<span class='muted'>Void</span>";
      hist.appendChild(row([esc(b.name)+"<span class='sub'>"+b.date+"</span>", label[b.market], am(b.price!=null?b.price:null), res]));
    });
  }
  fetch("data/sim_log.json",{cache:"no-store"})
    .then(function(r){if(!r.ok) throw 0; return r.json();})
    .then(function(log){ if(!log.length) throw 0; $("app").hidden=false; render(log); })
    .catch(function(){ $("empty").hidden=false; });
})();
