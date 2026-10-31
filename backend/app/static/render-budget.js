// Resolution policy is independent of scene detail and simulator timing.
export function createRenderBudget({initialRatio=1,maxRatio=1.5,minRatio=.75,warmupMs=3000}={}){
  let ratio=Math.min(maxRatio,Math.max(minRatio,initialRatio)),decisionAt=0,warmUntil=warmupMs,sum=0,count=0,headroom=0;
  return {get ratio(){return ratio;},
    reset(now,nextRatio=ratio){ratio=Math.min(maxRatio,Math.max(minRatio,nextRatio));decisionAt=now;warmUntil=now+warmupMs;sum=0;count=0;headroom=0;},
    sample(now,frameMs){
      if(!Number.isFinite(frameMs)||frameMs<=0||frameMs>500){decisionAt=now;sum=0;count=0;headroom=0;return null;}
      if(now<warmUntil)return null;
      sum+=frameMs;count++;if(now-decisionAt<2000 || count<8)return null;
      const average=sum/count;sum=0;count=0;decisionAt=now;let next=ratio;
      if(average>30){next=Math.max(minRatio,Math.round(ratio*.85*100)/100);headroom=0;}
      else if(average<17){if(++headroom>=3){next=Math.min(maxRatio,Math.round((ratio+.05)*100)/100);headroom=0;}}
      else headroom=0;
      if(next===ratio)return null;ratio=next;return ratio;
    }
  };
}
