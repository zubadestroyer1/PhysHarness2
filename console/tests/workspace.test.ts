import { createApiClient, loadWorkspace } from '../src/api'
import { refreshWorkspace } from '../src/workspace'
import { emptyWorkspace, type EventPage, type EventRecord } from '../src/types'

const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}})
const page=(cursor:number,items:EventRecord[]=[],more=false):EventPage=>({items,next_cursor:cursor,has_more:more,window:'forward',scan_limited:more})
const event=(sequence:number,kind:string,aggregate_id:string,payload:Record<string,unknown>={revision:2}):EventRecord=>({sequence,kind,aggregate_id,payload,operation_id:`op-${sequence}`,created_at:'2026-09-14T00:00:00Z'})
const record=(id:string,revision=1)=>({id,revision,project_id:'project',created_at:'2026-09-14T00:00:00Z'})
const status={version:'0.1.0',mode:'local',checks:[],qualifications:[]}

it('captures the initial watermark before any collection snapshot requests',async()=>{
 let release!:(value:Response)=>void
 const fetcher=vi.fn((input:RequestInfo|URL)=>{
  if(String(input).includes('/events'))return new Promise<Response>(resolve=>{release=resolve})
  return Promise.resolve(json(String(input).endsWith('/status')?status:{items:[]}))
 })
 const result=loadWorkspace(createApiClient({baseUrl:'',token:'test',fetcher}))
 expect(fetcher.mock.calls.map(([url])=>String(url))).toEqual(['/v1/events?tail=true&limit=100'])
 release(json({...page(27),window:'latest'}))
 expect((await result).eventPage?.next_cursor).toBe(27)
 expect(fetcher).toHaveBeenCalledTimes(12)
})

it('advances empty visible event pages and processes only one bounded page per refresh',async()=>{
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>json(String(input).includes('/events')?page(5000,[],true):status))
 const current={...emptyWorkspace,eventPage:page(0)}
 const next=await refreshWorkspace(createApiClient({baseUrl:'',token:'test',fetcher}),current)
 expect(next.eventPage).toEqual(page(5000,[],true))
 expect(fetcher.mock.calls.map(([url])=>String(url))).toEqual(['/v1/events?after=0&limit=100','/v1/status'])
})

it('refreshes only the affected experiment and retries the same cursor after a failed canonical read',async()=>{
 let broken=true
 const current={...emptyWorkspace,eventPage:page(4)}
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
  const path=String(input)
  if(path.includes('/events'))return json(page(5,[event(5,'experiment.paused','e1')]))
  if(path.endsWith('/experiments/e1'))return broken?json({error:{code:'READ_FAILED',message:'Retry this read'}},503):json({...record('e1',2),status:'paused'})
  return json(status)
 })
 const api=createApiClient({baseUrl:'',token:'test',fetcher})
 await expect(refreshWorkspace(api,current)).rejects.toMatchObject({code:'READ_FAILED'})
 expect(current.eventPage.next_cursor).toBe(4)
 broken=false
 const next=await refreshWorkspace(api,current)
 expect(fetcher.mock.calls.filter(([url])=>String(url)==='/v1/events?after=4&limit=100')).toHaveLength(2)
 expect(fetcher.mock.calls.every(([url])=>/events|experiments\/e1|status/.test(String(url)))).toBe(true)
 expect(next.experiments).toMatchObject([{id:'e1',status:'paused',revision:2}])
 expect(next.eventPage?.next_cursor).toBe(5)
})

it('refreshes verification claims within the affected experiment and follows all collection pages',async()=>{
 const other={...record('other'),experiment_id:'e2',statement:'Other campaign claim',assumptions:[],evidence:'conditional' as const}
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
  const path=String(input)
  if(path.includes('/events'))return json(page(6,[event(6,'verification.verified','v1',{experiment_id:'e1'})]))
  if(path.includes('/claims'))return json(path.includes('after=')?{items:[{...record('cl1'),experiment_id:'e1'}],next_cursor:null}:{items:[],next_cursor:'scanned'})
  return json(status)
 })
 const next=await refreshWorkspace(createApiClient({baseUrl:'',token:'test',fetcher}),{...emptyWorkspace,eventPage:page(5),claims:[other]})
 expect(next.claims.map(item=>item.id)).toEqual(['other','cl1'])
 expect(fetcher.mock.calls.map(([url])=>String(url))).toContain('/v1/claims?experiment_id=e1&after=scanned')
 expect(fetcher.mock.calls.some(([url])=>String(url)==='/v1/claims')).toBe(false)
})

it('waits for sibling reads to settle on failure so the next cycle cannot overlap them',async()=>{
 let release!:(value:Response)=>void
 const fetcher=vi.fn((input:RequestInfo|URL)=>{
  const path=String(input)
  if(path.includes('/events'))return Promise.resolve(json(page(5,[event(5,'experiment.paused','e1')])))
  if(path.endsWith('/status'))return new Promise<Response>(resolve=>{release=resolve})
  return Promise.resolve(json({error:{code:'READ_FAILED',message:'Read failed'}},503))
 })
 let settled=false
 const result=refreshWorkspace(createApiClient({baseUrl:'',token:'test',fetcher}),{...emptyWorkspace,eventPage:page(4)}).catch(()=>{settled=true})
 await new Promise(resolve=>setTimeout(resolve,0))
 expect(settled).toBe(false)
 release(json(status))
 await result
 expect(settled).toBe(true)
})

it('bounds recent Activity to 1,000 events without truncating inventories or changing the forward cursor',async()=>{
 let high=0
 const claims=Array.from({length:1200},(_,index)=>({...record(`claim-${index}`),experiment_id:'e1',statement:'Recorded evidence',assumptions:[],evidence:'conditional' as const}))
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
  if(!String(input).includes('/events'))return json(status)
  const after=Number(new URL(String(input),'http://localhost').searchParams.get('after'))
  const events=Array.from({length:Math.min(high-after,100)},(_,index)=>event(after+index+1,'resources.reserved','e1'))
  return json(page(events.at(-1)?.sequence??after,events))
 })
 const api=createApiClient({baseUrl:'',token:'test',fetcher})
 let current={...emptyWorkspace,eventPage:page(0),claims}
 for(let count=1;count<=15;count++) {
  high=count*100
  current=await refreshWorkspace(api,current) as typeof current
  expect(current.eventPage.next_cursor).toBe(high)
 }
 expect(current.events).toHaveLength(1000)
 expect(current.events.map(item=>item.sequence)).toEqual(Array.from({length:1000},(_,index)=>index+501))
 expect(current.claims).toBe(claims)
 expect(current.claims).toHaveLength(1200)
 const idle=await refreshWorkspace(api,current)
 expect(idle.events).toBe(current.events)
 expect(idle.eventPage?.next_cursor).toBe(1500)
 expect(fetcher.mock.calls.at(-2)?.[0]).toBe('/v1/events?after=1500&limit=100')
})

it('reuses the retained Activity window on an empty page while advancing the independent scanned cursor',async()=>{
 const events=[event(10,'resources.reserved','e1')]
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>json(String(input).includes('/events')?page(5000,[],true):status))
 const next=await refreshWorkspace(createApiClient({baseUrl:'',token:'test',fetcher}),{...emptyWorkspace,eventPage:page(10),events})
 expect(next.events).toBe(events)
 expect(next.eventPage).toEqual(page(5000,[],true))
})

it('incrementally creates and updates canonical session state on session.saved events',async()=>{
 let revision=1
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
  const path=String(input)
  if(path.includes('/events'))return json(page(revision,[event(revision,'session.saved','canonical-session',{experiment_id:'e1',task_id:'t1',revision})]))
  if(path.endsWith('/sessions/canonical-session'))return json({...record('canonical-session',revision),experiment_id:'e1',task_id:'t1',status:revision===1?'running':'completed',native_record_id:'native-session'})
  return json(status)
 })
 const api=createApiClient({baseUrl:'',token:'test',fetcher})
 const created=await refreshWorkspace(api,{...emptyWorkspace,eventPage:page(0)})
 expect(created.sessions).toMatchObject([{id:'canonical-session',revision:1,status:'running'}])
 revision=2
 const updated=await refreshWorkspace(api,created)
 expect(updated.sessions).toMatchObject([{id:'canonical-session',revision:2,status:'completed'}])
 expect(updated.sessions).toHaveLength(1)
 expect(fetcher.mock.calls.some(([url])=>String(url)==='/v1/sessions')).toBe(false)
})
