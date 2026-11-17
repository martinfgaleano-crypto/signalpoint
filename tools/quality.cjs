'use strict';
// Portable publication checks. These checks do not prove factual accuracy;
// evidence review and provider-side instruction isolation remain necessary.
const CATEGORIES = new Set(['Central banks','Macro data','Earnings','M&A','Corporate','Regulation','Commodities','Geopolitics','Other']);
const IMPACTS = new Set(['favorable','adverse','mixed','undetermined']);
const KEYS = new Set(['title','category','region','eventDate','evidence','source','summary','actors','watch','unknowns','tags','es']);
const ES_KEYS = new Set(['title','summary','actors','watch','unknowns']);
const nonempty = x => typeof x === 'string' && x.trim().length > 0;
const CHECKPOINT_KEYS = new Set(['text','due','kind','status','expect','note','outcome']);
function dateValid(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
  const n = Date.parse(value + 'T00:00:00Z');
  return Number.isFinite(n) && new Date(n).toISOString().slice(0,10) === value;
}
function canonicalUrl(value) {
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || u.username || u.password) return null;
    u.hash = '';
    for (const k of [...u.searchParams.keys()]) if (/^(utm_.+|fbclid|gclid)$/i.test(k)) u.searchParams.delete(k);
    u.searchParams.sort();
    u.pathname = u.pathname.replace(/\/$/, '') || '/';
    return u.toString();
  } catch { return null; }
}
function eventKey(b) {
  return [b.eventDate, String(b.title || '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim()].join('|');
}
function validateCheckpoint(w) {
  const errors=[];
  if (!w || typeof w!=='object' || Array.isArray(w)) return ['checkpoint must be an object'];
  if (Object.keys(w).some(k=>!CHECKPOINT_KEYS.has(k))) errors.push('unexpected checkpoint field');
  if (!nonempty(w.text) || (w.due!==''&&!dateValid(w.due))) errors.push('invalid checkpoint text or due date');
  const states=w.kind==='observation'?['open','observed','not_observed','inconclusive']:w.kind==='prediction'?['open','supported','refuted','inconclusive']:[];
  if (!states.includes(w.status)) errors.push('checkpoint kind and status must agree');
  if (w.kind==='prediction'&&!nonempty(w.expect)) errors.push('prediction requires explicit expectation');
  if (w.kind==='observation'&&w.expect!=null) errors.push('observation cannot imply a prediction');
  if (w.note!==undefined&&!nonempty(w.note)) errors.push('checkpoint note must contain text');
  if (w.outcome!==undefined&&!nonempty(w.outcome)) errors.push('checkpoint outcome must contain text');
  if (w.status!=='open'&&states.includes(w.status)) {
    const outcome=typeof w.outcome==='string'?w.outcome:'';
    // Existing artifact outcomes are dated prose with a URL. Require both;
    // a source and a date do not by themselves prove the outcome is correct.
    const url=outcome.match(/https:\/\/[^\s<>]+/)?.[0]?.replace(/[).,;]+$/,'');
    const iso=outcome.match(/\b\d{4}-\d{2}-\d{2}\b/)?.[0];
    const named=outcome.match(/\b(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}\b/)?.[0];
    let namedValid=false;
    if(named){const parsed=new Date(named+' 00:00:00 UTC');namedValid=Number.isFinite(+parsed)&&parsed.toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric',timeZone:'UTC'})===named;}
    if (!canonicalUrl(url)||!(iso?dateValid(iso):namedValid)) errors.push('closed checkpoint requires dated outcome and HTTPS evidence URL');
  }
  return errors;
}
function validateBrief(b, {today = new Date().toISOString().slice(0,10), maxAgeDays = null} = {}) {
  const errors = [];
  if (!b || typeof b !== 'object' || Array.isArray(b)) return {ok:false,errors:['brief must be an object']};
  for (const key of Object.keys(b)) if (!KEYS.has(key)) errors.push('unexpected field: '+key);
  if (b.es !== undefined) {
    const e = b.es;
    if (!e || typeof e !== 'object' || Array.isArray(e) || Object.keys(e).some(k=>!ES_KEYS.has(k))) errors.push('invalid translation');
    else {
      if (e.title !== undefined && (!nonempty(e.title) || e.title.length > 160)) errors.push('invalid translated title');
      if (e.summary !== undefined && !nonempty(e.summary)) errors.push('invalid translated summary');
      if (e.actors !== undefined && (!Array.isArray(e.actors) || !Array.isArray(b.actors) || e.actors.length !== b.actors.length || !e.actors.every(a=>a && nonempty(a.name) && nonempty(a.reason) && Object.keys(a).every(k=>k==='name'||k==='reason')))) errors.push('invalid translated actors');
      if (e.watch !== undefined && (!Array.isArray(e.watch) || !Array.isArray(b.watch) || e.watch.length !== b.watch.length || !e.watch.every(w=>w && nonempty(w.text) && Object.keys(w).every(k=>k==='text'||k==='note') && (w.note===undefined||typeof w.note==='string')))) errors.push('invalid translated checkpoints');
      if (e.unknowns !== undefined && (!Array.isArray(e.unknowns) || !e.unknowns.every(nonempty))) errors.push('invalid translated uncertainties');
    }
  }
  for (const key of ['title','region','summary']) if (!nonempty(b[key])) errors.push(key+' is required');
  if (typeof b.title === 'string' && b.title.length > 110) errors.push('title exceeds 110 characters');
  if (!CATEGORIES.has(b.category)) errors.push('invalid category');
  if (!dateValid(b.eventDate)) errors.push('eventDate must be a real date');
  else if (!dateValid(today) || b.eventDate > today) errors.push('eventDate is in the future or reference date is invalid');
  else if (maxAgeDays != null && (Date.parse(today)-Date.parse(b.eventDate))/864e5 > maxAgeDays) errors.push('event is outside freshness window');
  if (!['A','B','C'].includes(b.evidence)) errors.push('invalid evidence grade');
  if (!b.source || !nonempty(b.source.name) || !canonicalUrl(b.source.url)) errors.push('a named HTTPS source is required');
  if (!Array.isArray(b.actors) || !b.actors.length || b.actors.length > 5) errors.push('one to five actors required');
  else b.actors.forEach((a,i) => {
    if (!a || !nonempty(a.name) || !nonempty(a.reason) || !IMPACTS.has(a.impact) || typeof a.ticker !== 'string') errors.push('invalid actor '+i);
  });
  if (!Array.isArray(b.watch) || b.watch.length < 2 || b.watch.length > 4) errors.push('two to four checkpoints required');
  else b.watch.forEach((w,i) => {
    errors.push(...validateCheckpoint(w).map(e=>'checkpoint '+i+': '+e));
  });
  if (!Array.isArray(b.unknowns) || b.unknowns.length < 2 || b.unknowns.length > 4 || !b.unknowns.every(nonempty)) errors.push('two to four uncertainties required');
  if (!Array.isArray(b.tags) || b.tags.length > 6 || !b.tags.every(nonempty)) errors.push('invalid tags');
  const text = [b.title,b.summary,...(Array.isArray(b.actors)?b.actors.map(a=>a?.reason):[]),...(Array.isArray(b.unknowns)?b.unknowns:[])].join(' ');
  if (/\[Synthetic Batch\]|\{\{record\.|\b(?:TODO|TBD)\b/i.test(text)) errors.push('placeholder or test content');
  if (/\b(?:you|investors|traders)\s+(?:should|must)\s+(?:buy|sell|short)\b|\bwe recommend\s+(?:buying|selling|shorting)\b|\bis a (?:strong )?buy\b|\b(?:our|my) price target\b|\bconfidence\s*(?:of|is|:)?\s*\d+(?:\.\d+)?\s*%/i.test(text)) errors.push('investment recommendation or model confidence language');
  return {ok:errors.length===0, errors};
}
function selectCandidates(candidates, existing, options={}) {
  // This registry is operator configuration, never model output. A daily
  // bulletin may support several distinct events without being a duplicate.
  const collectionUrls=new Set((options.collectionSourceUrls||[]).map(canonicalUrl).filter(Boolean));
  const seenUrls=new Set(existing.map(b=>canonicalUrl(b.source?.url)).filter(Boolean));
  const seenEvents=new Set(existing.map(eventKey));
  const accepted=[], rejected=[];
  for (const candidate of candidates) {
    const check=validateBrief(candidate,options);
    if (!check.ok) { rejected.push({title:candidate?.title || '',reasons:check.errors}); continue; }
    const url=canonicalUrl(candidate.source.url), key=eventKey(candidate);
    if ((seenUrls.has(url)&&!collectionUrls.has(url))||seenEvents.has(key)) { rejected.push({title:candidate.title,reasons:['duplicate URL or event']}); continue; }
    seenUrls.add(url); seenEvents.add(key); accepted.push(candidate);
  }
  return {accepted,rejected};
}
function predictionStats(items) {
  const resolved=items.filter(w=>w.kind==='prediction' && nonempty(w.expect) && ['supported','refuted'].includes(w.status));
  const supported=resolved.filter(w=>w.status==='supported').length;
  return {resolved:resolved.length,supported,rate:resolved.length?supported/resolved.length:null};
}
function validateMove(doc,brief){
  const errors=[];
  if(!doc||typeof doc!=='object'||Array.isArray(doc))return {ok:false,errors:['move document must be an object']};
  if(Object.keys(doc).some(k=>!['items','sourceUrl'].includes(k)))errors.push('unexpected move document field');
  if(!brief||doc.sourceUrl!==brief.source?.url||!canonicalUrl(doc.sourceUrl))errors.push('move source must equal brief source');
  if(!Array.isArray(doc.items)||!doc.items.length||doc.items.length>4)return {ok:false,errors:errors.concat('one to four moves required')};
  const drivers=new Set(),summary=String(brief?.summary||'');
  const figures=[...summary.matchAll(/(?<![\d.])(-?\d+(?:\.\d+)?)\s*%/g)].map(m=>Number(m[1]));
  for(const m of doc.items){
    if(!m||Object.keys(m).some(k=>!['driver','label','change','unit','period','basis'].includes(k))||
      !['US10Y','FED_TARGET','CRUDE','WHEAT','US_CPI','US_PPI','CO_CPI','COLCAP','USDCOP'].includes(m.driver)||!nonempty(m.label)||!nonempty(m.period)||
      !['official','reported'].includes(m.basis)||typeof m.change!=='number'||!Number.isFinite(m.change)||m.change===0||Math.abs(m.change)>100||
      m.unit!==(['US10Y','FED_TARGET'].includes(m.driver)?'pp':'%')){errors.push('invalid move');continue;}
    if(drivers.has(m.driver))errors.push('duplicate driver');drivers.add(m.driver);
    if(m.basis==='official'&&brief?.evidence!=='A')errors.push('official move requires evidence A');
    if(m.unit==='%'){
      const literal=String(Math.abs(m.change)).replace('.', '\\.');
      if(!new RegExp('(?<![\\d.])'+literal+'%(?![\\d])').test(summary))errors.push('move figure is absent from brief summary');
    }else if(m.driver==='FED_TARGET'){
      if(m.basis!=='official'||brief?.evidence!=='A'||!/^https:\/\/www\.federalreserve\.gov\//.test(doc.sourceUrl))errors.push('Fed target moves require a primary Federal Reserve source and evidence A');
      // Range width is not a policy change. Require an explicit old → new range.
      const transition=summary.match(/from\s+(\d+(?:\.\d+)?)%?\s*[-–]\s*(\d+(?:\.\d+)?)%\s+to\s+(\d+(?:\.\d+)?)%?\s*[-–]\s*(\d+(?:\.\d+)?)%/i);
      if(!transition||/\b(?:holds?|held|maintains?|maintained|unchanged)\b/i.test(summary)||
         Math.abs(Number(transition[3])-Number(transition[1])-m.change)>1e-8||
         Math.abs(Number(transition[4])-Number(transition[2])-m.change)>1e-8)errors.push('Fed move requires an actual, equal shift of both quoted range endpoints');
    }else{
      // Direction follows later minus earlier as ordered in the prose: both quoted yields must exist.
      if(!figures.some((later,i)=>figures.slice(i+1).some(earlier=>Math.abs(later-earlier-m.change)<1e-8)))errors.push('percentage-point move is not supported by quoted figures');
    }
  }
  return {ok:errors.length===0,errors};
}
module.exports={validateBrief,validateCheckpoint,selectCandidates,predictionStats,dateValid,canonicalUrl,eventKey,validateMove};
