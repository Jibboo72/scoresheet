(function(){
  // Grades the same nightly props as singles and round robins, $33 a night each.
  // A parlay lives at one book, so each combo is priced at the single book that pays most for it.
  var BUDGET=33, SIZES=[6,8,12], size=8, LOG=[], MAX_PRICE=750; // longer prices never make the slate
  var STRATS=[{id:"value",label:"Best value"},{id:"likely",label:"Most likely"}], strat="value";
  var OFFSHORE=["Bovada","BetOnline.ag","MyBookie.ag","BetUS","LowVig.ag"]; // never used, even in old logs
  var STRUCTS=[{name:"Singles",k:[1]},{name:"2-pick round robin",k:[2]},
               {name:"3-pick round robin",k:[3]},{name:"2s + 3s round robin",k:[2,3]}];
  var $=function(id){return document.getElementById(id)};
  var money=function(v){return (v<0?"-$":"+$")+Math.abs(v).toFixed(0)};
  var am=function(p){return p>0?"+"+p:""+p};
  var esc=function(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})};
  var label={goal:"goal",assist:"assist"};
  function dec(p){return p>0?1+p/100:1+100/Math.abs(p)}
  function toAm(d){return d>=2?Math.round((d-1)*100):-Math.round(100/(d-1))}
  function books(b){ // this prop's prices at your books (board.py only pulls your books)
    var src=b.prices||(b.book?(function(){var o={}; o[b.book]=b.price; return o})():{}), out={};
    Object.keys(src).forEach(function(k){if(OFFSHORE.indexOf(k)<0) out[k]=src[k]});
    return out;
  }
  function combos(n,k){
    var out=[];
    (function rec(start,acc){
      if(acc.length===k){out.push(acc.slice());return}
      for(var i=start;i<n;i++){acc.push(i);rec(i+1,acc);acc.pop()}
    })(0,[]);
    return out;
  }
  // Best single book for a set of props: {book, dec} or null if no book offers them all.
  function route(legs){
    var best=null;
    Object.keys(legs[0].px).forEach(function(bk){
      if(!legs.every(function(l){return bk in l.px})) return;
      var d=legs.reduce(function(t,l){return t*dec(l.px[bk])},1);
      if(!best||d>best.dec) best={book:bk, dec:d, legs:legs};
    });
    return best;
  }
  function tickets(legs,ks){
    var out=[];
    ks.forEach(function(k){ if(legs.length>=k) combos(legs.length,k).forEach(function(c){
      var r=route(c.map(function(i){return legs[i]})); if(r) out.push(r);
    })});
    return out;
  }
  // Every 2-pick and 3-pick combo with this new prop must have one book offering all its legs.
  function fits(out,leg){
    for(var i=0;i<out.length;i++){
      if(!route([out[i],leg])) return false;
      for(var j=i+1;j<out.length;j++) if(!route([out[i],out[j],leg])) return false;
    }
    return true;
  }
  // Which props a strategy can use. Best value: 5%+ edge at +750 or shorter, flagged plays left out.
  // Most likely: the likely-to-hit pool (high chance, +200 or shorter, price checked), best price first.
  function eligible(b){
    if(b.price==null||!Object.keys(books(b)).length) return false;
    return strat==="likely" ? !!b.likely : b.kind==="bet"&&!b.flag&&b.price<=MAX_PRICE;
  }
  // Top props by edge: one per player, at most two per game.
  // A prop that can't share a book with the props already picked is skipped for the next best one,
  // so every round robin combo can be placed and none get dropped.
  function slate(bets){
    var players={}, games={}, out=[];
    bets.filter(eligible)
      .sort(function(a,b){return b.ev-a.ev}).forEach(function(b){
        if(out.length>=size||players[b.player_id]||(games[b.game_id]||0)>=2) return;
        var leg={b:b, px:books(b)};
        if(!fits(out,leg)) return;
        players[b.player_id]=1; games[b.game_id]=(games[b.game_id]||0)+1;
        out.push(leg);
      });
    return out;
  }
  function nightProfit(legs,ks){
    var t=tickets(legs,ks); if(!t.length) return null;
    var stake=BUDGET/t.length, ret=0;
    t.forEach(function(tk){
      var r=tk.legs.reduce(function(m,l){
        return m*(l.b.status==="win"?dec(l.px[tk.book]):l.b.status==="void"?1:0)},1);
      ret+=r*stake;
    });
    return ret-BUDGET;
  }
  function render(){
    var sc=$("strats");
    if(!sc){sc=document.createElement("div"); sc.id="strats"; sc.className="chips"; $("sizes").parentNode.insertBefore(sc,$("sizes"))}
    sc.innerHTML="";
    STRATS.forEach(function(s){
      var b=document.createElement("button"); b.textContent=s.label;
      b.setAttribute("aria-pressed", s.id===strat?"true":"false");
      b.onclick=function(){strat=s.id; render()};
      sc.appendChild(b);
    });
    var chips=$("sizes"); chips.innerHTML="";
    SIZES.forEach(function(n){
      var b=document.createElement("button"); b.textContent=n+" props";
      b.setAttribute("aria-pressed", n===size?"true":"false");
      b.onclick=function(){size=n; render()};
      chips.appendChild(b);
    });
    var byDate={}; LOG.forEach(function(b){(byDate[b.date]=byDate[b.date]||[]).push(b)});
    var graded=[], pending=null;
    Object.keys(byDate).sort().forEach(function(d){
      var s=slate(byDate[d]); if(!s.length) return;
      if(s.some(function(l){return l.b.status==="pending"})) pending={date:d, legs:s}; else graded.push(s);
    });
    var tb=$("structs"); tb.innerHTML="";
    var rows=STRUCTS.map(function(st){
      var cum=0, peak=0, slump=0, wins=0, nights=0;
      graded.forEach(function(legs){
        var p=nightProfit(legs,st.k); if(p===null) return;
        nights++; cum+=p; if(p>0) wins++; peak=Math.max(peak,cum); slump=Math.max(slump,peak-cum);
      });
      return {st:st, profit:cum, nights:nights, wins:wins, slump:slump};
    });
    var best=rows.reduce(function(a,r){return r.nights&&(!a||r.profit>a.profit)?r:a},null);
    rows.forEach(function(r){
      var tr=document.createElement("tr"), roi=r.nights?r.profit/(r.nights*BUDGET):null;
      tr.innerHTML="<td"+(r===best&&graded.length?" class='lead'":"")+">"+r.st.name+"</td>"+
        "<td class='"+(r.profit>=0?"up":"down")+"'>"+(r.nights?money(r.profit):"—")+"</td>"+
        "<td>"+(roi==null?"—":(roi>0?"+":"")+(roi*100).toFixed(1)+"%")+"</td>"+
        "<td>"+(r.nights?r.wins+"/"+r.nights:"—")+"</td>"+
        "<td>"+(r.nights?"$"+r.slump.toFixed(0):"—")+"</td>";
      tb.appendChild(tr);
    });
    $("structNote").textContent = !graded.length
      ? (strat==="likely" ? "Most likely started Oct 9. Results show up the day after its first night." : "Nothing graded yet. The first results show up the day after the first priced night.")
      : graded.length<20 ? graded.length+" night"+(graded.length===1?"":"s")+" graded. The gaps between structures mean little before about 20 nights."
      : graded.length+" nights graded.";
    var ol=$("slate"); ol.innerHTML="";
    if(!pending){$("slateMeta").textContent="No slate waiting on results."; return}
    var legs=pending.legs, t=tickets(legs,[2]), per={};
    t.forEach(function(tk){per[tk.book]=(per[tk.book]||0)+1});
    $("slateMeta").textContent=legs.length+" props for "+pending.date+". 2-pick round robin: "+t.length+" parlays at $"+
      (t.length?(BUDGET/t.length).toFixed(2):"0")+" each ("+Object.keys(per).map(function(k){return per[k]+" at "+k}).join(", ")+").";
    legs.forEach(function(l){
      var b=l.b, li=document.createElement("li"); li.className="play";
      li.innerHTML="<span class='who'>"+esc(b.name)+"</span><span class='game'>"+b.team+" vs "+b.opp+", "+label[b.market]+"</span>"+
        "<span class='nums'>"+Object.keys(l.px).map(function(k){return k+" <b>"+am(l.px[k])+"</b>"}).join(", ")+"</span>"+
        "<span class='ev'><b>"+(b.ev>0?"+":"")+(b.ev*100).toFixed(0)+"%</b><span>EV</span></span>";
      ol.appendChild(li);
    });
    var slip=$("slip"); slip.innerHTML="";
    t.sort(function(a,b){return a.book<b.book?-1:a.book>b.book?1:b.dec-a.dec}).forEach(function(tk){
      var tr=document.createElement("tr");
      tr.innerHTML="<td>"+tk.legs.map(function(l){return esc(l.b.name.split(" ").slice(-1)[0])+" "+label[l.b.market]}).join(" + ")+
        "</td><td>"+tk.book+"</td><td>"+am(toAm(tk.dec))+"</td>";
      slip.appendChild(tr);
    });
    $("slipBlock").hidden=!t.length;
  }
  fetch("data/sim_log.json",{cache:"no-store"})
    .then(function(r){if(!r.ok) throw 0; return r.json()})
    .then(function(log){
      LOG=log; if(!log.some(function(b){return b.kind==="bet"||b.likely})) return;
      $("structBlock").hidden=false; render();
    })
    .catch(function(){});
})();
