import { act, fireEvent, render, screen, within } from '@testing-library/react'
import App from '../src/App'
import type { Artifact, Campaign, Experiment } from '../src/types'

const core = {project_id:'project',revision:1,created_at:'2026-09-14T00:00:00Z'}
const campaign: Campaign = {...core,id:'c1',title:'Rigidity',objective:'Target',programs:['quantum']}
const experiment: Experiment = {...core,id:'e1',campaign_id:'c1',problem_id:'p1',models:[{runtime:'codex-sdk',model:'research-model',parameters:{}}],budget:{max_cost_usd:'5.00',max_concurrency:1,max_runtime_seconds:60},policy:'direct',mode:'research',status:'running',target_digest:'a'.repeat(64)}
const artifact = (id:string):Artifact=>({...core,id,experiment_id:'e1',artifact_kind:id,media_type:'text/plain',provenance:{},sha256:'b'.repeat(64)})
const json = (body:unknown)=>new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}})
function deferred() {let resolve!:(value:Response)=>void; const promise=new Promise<Response>(done=>{resolve=done});return {promise,resolve}}
function setup() {
 sessionStorage.setItem('physharness.token','token')
 const fetcher=vi.fn(async (input:RequestInfo|URL,_init?:RequestInit)=>{
  const path=String(input)
  if(path.endsWith('/status'))return json({version:'0.1.0',mode:'local',checks:[],qualifications:[]})
  if(path.includes('/events'))return json({items:[],next_cursor:0,has_more:false,window:path.includes('tail=true')?'latest':'forward',scan_limited:false})
  if(path.endsWith('/campaigns'))return json({items:[campaign]})
  if(path.endsWith('/experiments'))return json({items:[experiment]})
  if(path.endsWith('/artifacts'))return json({items:[artifact('artifact-a'),artifact('artifact-b')]})
  if(path.endsWith('/ledger'))return json({max_cost_usd:'5.00',spent_cost_usd:'0.00',reserved_cost_usd:'0.00',active_workers:0,max_concurrency:1,uncertain_operations:[]})
  if(path.endsWith('/content'))return json({content:path.includes('artifact-a')?'content A':'content B'})
  return json({items:[]})
 })
 vi.stubGlobal('fetch',fetcher)
 return fetcher
}

it('ignores an old workspace response after disconnect and reconnect',async()=>{
 const fetcher=setup(), pending=deferred(), original=fetcher.getMockImplementation()!
 let calls=0
 fetcher.mockImplementation((input,init)=>{
  if(String(input).endsWith('/campaigns')&&calls++===0)return pending.promise
  return original(input,init)
 })
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'Disconnect'}))
 fireEvent.change(screen.getByLabelText(/bearer token/i),{target:{value:'new-token'}})
 fireEvent.click(screen.getByRole('button',{name:'Connect'}))
 await act(async()=>{})
 await act(async()=>{pending.resolve(json({items:[{...campaign,id:'old',title:'Old session'}]}))})
 expect(screen.queryByText('Old session')).not.toBeInTheDocument()
 expect(screen.getByRole('heading',{name:'Rigidity'})).toBeInTheDocument()
})

it('keeps artifact content bound to its ID when a previous selection completes late',async()=>{
 const fetcher=setup(), pending=deferred(), original=fetcher.getMockImplementation()!
 fetcher.mockImplementation((input,init)=>String(input).includes('/artifact-a/content')?pending.promise:original(input,init))
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'Claims & branches'}))
 fireEvent.click(screen.getByRole('button',{name:/artifact-a/}))
 fireEvent.click(screen.getByRole('button',{name:/artifact-b/}))
 await act(async()=>{})
 await act(async()=>{pending.resolve(json({content:'content A'}))})
 const panel=screen.getByRole('complementary',{name:/evidence detail/i})
 expect(within(panel).getByText('content B')).toBeInTheDocument()
 expect(within(panel).queryByText('content A')).not.toBeInTheDocument()
})

it('does not reopen the previous experiment when its mutation finishes after reselection',async()=>{
 const fetcher=setup(), pending=deferred(), original=fetcher.getMockImplementation()!
 fetcher.mockImplementation((input,init)=>init?.method==='POST'?pending.promise:original(input,init))
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/cancel experiment/i}))
 fireEvent.click(screen.getByRole('button',{name:'Claims & branches'}))
 fireEvent.click(screen.getByRole('button',{name:/artifact-b/}))
 await act(async()=>{})
 await act(async()=>{pending.resolve(json({...experiment,status:'cancelled',revision:2}))})
 expect(within(screen.getByRole('complementary',{name:/evidence detail/i})).getByText('content B')).toBeInTheDocument()
})

it('ignores a stale export response after closing and reopening the export dialog',async()=>{
 const fetcher=setup(), first=deferred(), second=deferred(), original=fetcher.getMockImplementation()!
 let exports=0
 fetcher.mockImplementation((input,init)=>String(input).endsWith('/export')?(exports++===0?first.promise:second.promise):original(input,init))
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/export reproducibility/i}))
 fireEvent.click(screen.getByRole('button',{name:/close dialog/i}))
 fireEvent.click(screen.getByRole('button',{name:/export reproducibility/i}))
 await act(async()=>{second.resolve(json({manifest:'new export'}))})
 await act(async()=>{first.resolve(json({manifest:'stale export'}))})
 expect(screen.getByText(/new export/)).toBeInTheDocument()
 expect(screen.queryByText(/stale export/)).not.toBeInTheDocument()
})

it('ignores an old ledger completion after selecting an artifact',async()=>{
 const fetcher=setup(), pending=deferred(), original=fetcher.getMockImplementation()!
 fetcher.mockImplementation((input,init)=>String(input).endsWith('/ledger')?pending.promise:original(input,init))
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'Claims & branches'}))
 fireEvent.click(screen.getByRole('button',{name:/artifact-b/}))
 await act(async()=>{})
 await act(async()=>{pending.resolve(json({spent_cost_usd:'99.00',reserved_cost_usd:'0.00',max_cost_usd:'100.00',active_workers:1,max_concurrency:1,uncertain_operations:[]}))})
 expect(screen.getByText('content B')).toBeInTheDocument()
 expect(screen.queryByText('$99.00')).not.toBeInTheDocument()
})

it('retains loaded artifact content when polling refreshes its canonical metadata',async()=>{
 const fetcher=setup(), original=fetcher.getMockImplementation()!
 let tick!:()=>void
 vi.spyOn(window,'setInterval').mockImplementation(((callback:()=>void)=>{tick=callback;return 999}) as typeof window.setInterval)
 fetcher.mockImplementation((input,init)=>{
  const path=String(input)
  if(path.includes('/events?after='))return Promise.resolve(json({items:[{sequence:1,kind:'artifact.created',aggregate_id:'artifact-b',operation_id:'op',created_at:core.created_at,payload:{}}],next_cursor:1,has_more:false,window:'forward',scan_limited:false}))
  if(path.endsWith('/artifacts/artifact-b'))return Promise.resolve(json({...artifact('artifact-b'),provenance:{checked:'canonical'}}))
  return original(input,init)
 })
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'Claims & branches'}))
 fireEvent.click(screen.getByRole('button',{name:/artifact-b/}))
 await act(async()=>{})
 await act(async()=>{tick()})
 expect(screen.getByText('content B')).toBeInTheDocument()
 expect(screen.getByText(/"checked": "canonical"/)).toBeInTheDocument()
 expect(fetcher.mock.calls.filter(([url])=>String(url).endsWith('/artifact-b/content'))).toHaveLength(1)
})
