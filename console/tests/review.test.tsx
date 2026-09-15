import { act, render, screen, within, cleanup, fireEvent } from '@testing-library/react'
import App from '../src/App'
import type { Experiment } from '../src/types'
const response = (body: unknown, status=200) => Promise.resolve(new Response(JSON.stringify(body), {status,headers:{'Content-Type':'application/json'}}))
const experiment: Experiment = {id:'e1',project_id:'p1',revision:1,created_at:'2026-09-14T00:00:00Z',campaign_id:'c1',problem_id:'p1',models:[{runtime:'codex-sdk',model:'research-model',parameters:{}}],budget:{max_cost_usd:'5.00',max_concurrency:1,max_runtime_seconds:60},policy:'direct',mode:'research',status:'running',target_digest:'a'.repeat(64)}
let tick: () => void
let revision = 1
let spent = '0.00'
let ledgerCalls = 0
beforeEach(() => {
 revision=1;spent='0.00';ledgerCalls=0;experiment.status='running'
 sessionStorage.setItem('physharness.token','token')
 vi.spyOn(window,'setInterval').mockImplementation(((cb: () => void) => {tick=cb;return 999}) as typeof window.setInterval)
 vi.stubGlobal('fetch',vi.fn((input: unknown, init?: RequestInit) => {
 const path=String(input)
 if(init?.method==='POST')return response({error:{code:'STALE_REVISION',message:'Experiment changed',remediation:'Reload before cancelling.',retryable:true}},409)
 if(path.endsWith('/v1/status'))return response({version:'0.1.0',mode:'local',checks:[],qualifications:[]})
 if(path.endsWith('/v1/campaigns'))return response({items:[{id:'c1',project_id:'p1',revision:1,created_at:'2026-09-14T00:00:00Z',title:'Rigidity',objective:'Target',programs:['quantum']}]})
 if(path.includes('/v1/events'))return response({items:revision===1?[]:[{sequence:2,kind:'experiment.paused',aggregate_id:'e1',operation_id:'op-2',payload:{revision:2},created_at:'2026-09-14T00:00:00Z'}],next_cursor:revision,has_more:false,window:path.includes('tail=true')?'latest':'forward',scan_limited:false})
 if(path.endsWith('/v1/experiments/e1'))return response({...experiment,revision,status:revision===1?experiment.status:'paused'})
 if(path.endsWith('/v1/experiments'))return response({items:[{...experiment,revision,status:revision===1?experiment.status:'paused'}]})
 if(path.endsWith('/ledger')){ledgerCalls++;return response({spent_cost_usd:spent,reserved_cost_usd:'0.00',max_cost_usd:'5.00',active_workers:1,max_concurrency:1,uncertain_operations:[]})}
 return response({items:[]})
 }))
})
afterEach(()=>cleanup())
it('refreshes selected experiment revision and ledger on poll',async()=>{
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 const panel=screen.getByRole('complementary',{name:/evidence detail/i})
 expect(within(panel).getAllByText('$0.00',{selector:'dd'})).toHaveLength(2)
 revision=2;spent='3.00'
 await act(async()=>{tick()})
 expect(within(panel).getByText(/paused · revision 2/)).toBeInTheDocument()
 expect(within(panel).getByText('$3.00')).toBeInTheDocument()
})
it('preserves mutation failure when background refresh succeeds',async()=>{
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/cancel experiment/i}))
 await act(async()=>{})
 expect(screen.getByText('STALE_REVISION')).toBeInTheDocument()
 await act(async()=>{tick()})
 expect(screen.getByText('STALE_REVISION')).toBeInTheDocument()
})

it('allows cancellation of API queued experiment',async()=>{
 experiment.status='queued'
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 expect(screen.getByRole('button',{name:/cancel experiment/i})).toBeInTheDocument()
})

it('allows pause and cancellation in list and detail after starting a created experiment',async()=>{
 experiment.status='created'
 const original=vi.mocked(fetch).getMockImplementation()!
 vi.mocked(fetch).mockImplementation((input,init)=>{
  if(init?.method==='POST') {experiment.status='queued';return response({...experiment,revision:2})}
  return original(input,init)
 })
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'Experiments'}))
 fireEvent.click(screen.getByRole('button',{name:/start experiment/i}))
 await act(async()=>{})
 expect(screen.getByRole('button',{name:/pause experiment/i})).toBeInTheDocument()
 expect(screen.getByRole('button',{name:/cancel experiment/i})).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 const panel=screen.getByRole('complementary',{name:/evidence detail/i})
 expect(within(panel).getByRole('button',{name:/pause experiment/i})).toBeInTheDocument()
 expect(within(panel).getByRole('button',{name:/cancel experiment/i})).toBeInTheDocument()
})
it('allows resume and cancellation of blocked experiments',async()=>{
 experiment.status='blocked'
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 expect(screen.getByRole('button',{name:/resume experiment/i})).toBeInTheDocument()
 expect(screen.getByRole('button',{name:/cancel experiment/i})).toBeInTheDocument()
})
it('does not reload collections when the event cursor is unchanged, but refreshes the selected ledger',async()=>{
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 vi.mocked(fetch).mockClear()
 spent='2.00'
 await act(async()=>{tick()})
 expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).match(/\/v1\/(campaigns|problems|experiments|branches|tasks|claims|artifacts|reviews|sessions|programs)$/))).toHaveLength(0)
 expect(screen.getByText('$2.00')).toBeInTheDocument()
})
it('does not start an overlapping poll while a request is pending',async()=>{
 render(<App />)
 await act(async()=>{})
 const original=vi.mocked(fetch).getMockImplementation()!
 let finish!: (value:Response)=>void
 vi.mocked(fetch).mockImplementation((input,init)=>String(input).includes('/v1/events')?new Promise(resolve=>{finish=resolve}):original(input,init))
 vi.mocked(fetch).mockClear()
 await act(async()=>{tick();tick();tick()})
 expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).includes('/v1/events'))).toHaveLength(1)
 await act(async()=>{finish(await response({items:[],next_cursor:1,has_more:false,window:'forward',scan_limited:false}))})
})

it('reloads ledger when the same experiment is explicitly reselected',async()=>{
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 spent='1.50'
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 expect(screen.getByText('$1.50')).toBeInTheDocument()
})

it('uses the refreshed canonical revision for the next selected transition',async()=>{
 render(<App />)
 await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:/open experiment rigidity/i}))
 await act(async()=>{})
 revision=2
 await act(async()=>{tick()})
 fireEvent.click(screen.getByRole('button',{name:/cancel experiment/i}))
 await act(async()=>{})
 expect(fetch).toHaveBeenCalledWith('/v1/experiments/e1/transition',expect.objectContaining({body:JSON.stringify({action:'cancel',expected_revision:2})}))
})

it('labels historical sessions as project-wide recorded sessions and discloses the Activity limit',async()=>{
 const original=vi.mocked(fetch).getMockImplementation()!
 vi.mocked(fetch).mockImplementation((input,init)=>String(input).endsWith('/sessions')?response({items:[{id:'session-1',project_id:'p1',revision:2,created_at:'2026-09-14T00:00:00Z',status:'completed'}]}):original(input,init))
 render(<App />)
 await act(async()=>{})
 const metric=screen.getByText('Recorded sessions').closest('article')!
 expect(within(metric).getByText('1')).toBeInTheDocument()
 expect(within(metric).getByText('project-wide total')).toBeInTheDocument()
 expect(screen.queryByText('Active sessions')).not.toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'Activity'}))
 expect(screen.getByText(/1,000 newest observed events/)).toBeInTheDocument()
})
