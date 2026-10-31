import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../backend/app/static/render-budget.js',import.meta.url),'utf8');
const {createRenderBudget}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const budget=createRenderBudget({initialRatio:1.25,maxRatio:1.5,minRatio:.75,warmupMs:0});
let now=0,changes=[];
for(let i=0;i<100;i++){now+=60;const r=budget.sample(now,60);if(r!==null)changes.push(r);}
assert(changes.length>=2 && budget.ratio<1.25,'Sustained slow frames lower render resolution');
for(let i=0;i<500;i++){now+=60;budget.sample(now,60);}
assert.equal(budget.ratio,.75,'Automatic resolution has a lower bound');
const afterSlow=budget.ratio;
for(let i=0;i<100;i++){now+=12;budget.sample(now,12);}
assert.equal(budget.ratio,afterSlow,'Brief fast bursts do not cause resolution oscillation');
for(let i=0;i<800;i++){now+=12;budget.sample(now,12);}
assert(budget.ratio>afterSlow && budget.ratio<=1.5,'Sustained headroom restores detail gradually');
const beforePause=budget.ratio;
budget.sample(now+30000,30000);
assert.equal(budget.ratio,beforePause,'Tab suspension does not count as a slow frame');
budget.reset(now+30000,1);
assert.equal(budget.ratio,1,'Manual quality changes reset the automatic history');
console.log(JSON.stringify({passed:6,minimum:.75,maximum:1.5}));
