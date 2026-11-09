// Author inside Artifact Session, using its prebound presentation.
// This module does not create or export a separate presentation.
const ASSETS = decodeURIComponent(new URL('./assets', import.meta.url).pathname);
const C = { green:'#76B900', teal:'#008564', blue:'#0071C5', black:'#111111', gray:'#5E5E5E', mid:'#8C8C8C', line:'#CDCDCD', pale:'#F3F5F1', soft:'#EAF3DC', white:'#FFFFFF' };
const FONT = 'NVIDIA Sans';
const NO_LINE = {fill:'none',width:0};
const SRC = {
  outline:'WORKSHOP_OUTLINE.md, section 1 (October 30, 2026).',
  cache:'https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/',
  dgd:'configs/dgd/super-vl-tp2/nemotron-agg-functionality.yaml; excerpted structure only, not a new qualified manifest.',
  metrics:'https://github.com/ai-dynamo/aiperf',
  metricDefinitions:'https://docs.nvidia.com/aiperf/dev/reference/ai-perf-metrics-reference',
};

function shape(slide,name,x,y,w,h,fill=C.white,stroke='none',geometry='rect') {
  return slide.shapes.add({name,geometry,position:{left:x,top:y,width:w,height:h},fill,line:stroke==='none'?NO_LINE:{fill:stroke,width:1.6,style:'solid'}});
}
function text(slide,name,x,y,w,h,value,size=26,color=C.black,bold=false,align='left',font=FONT) {
  const s=shape(slide,name,x,y,w,h,'none'); s.geometry='textbox'; s.text=value;
  s.text.style={typeface:font,fontSize:size,color,bold,alignment:align,verticalAlignment:'middle',insets:0,wrap:'square',autoFit:'none',lineSpacing:1.12};
  return s;
}
function line(slide,name,x1,y1,x2,y2,color=C.line,width=2,dashed=false) {
  return slide.shapes.add({name,geometry:'line',position:{left:Math.min(x1,x2),top:Math.min(y1,y2),width:Math.abs(x2-x1),height:Math.abs(y2-y1)},fill:'none',line:{fill:color,width,style:dashed?'dashed':'solid'}});
}
function arrow(slide,name,x1,y1,x2,y2,color=C.gray,width=2.5,dashed=false) {
  const reverse=x2<x1 || (x2===x1 && y2<y1);
  return slide.shapes.add({name,geometry:'connector',kind:'straight',position:{left:Math.min(x1,x2),top:Math.min(y1,y2),width:Math.abs(x2-x1),height:Math.abs(y2-y1)},line:{fill:color,width,style:dashed?'dashed':'solid'},...(reverse?{head:{type:'triangle',width:'med',length:'med'}}:{tail:{type:'triangle',width:'med',length:'med'}})});
}
function box(slide,name,x,y,w,h,label,{fill=C.pale,stroke='none',color=C.black,size=27,bold=true}={}) {
  const b=shape(slide,name,x,y,w,h,fill,stroke);
  text(slide,`${name}-label`,x+18,y+10,w-36,h-20,label,size,color,bold,'center'); return b;
}
function icon(slide,file,x,y,w=42,h=42) {slide.images.add({path:`${ASSETS}/${file}`,alt:file.replace('.png','').replaceAll('-',' '),fit:'contain',position:{left:x,top:y,width:w,height:h}});}
function base(slide,index,title,subtitle,iconFile) {
  slide.background.fill=C.white;
  text(slide,`s${index}-title`,72,52,1050,66,title,44,C.black,true);
  shape(slide,`s${index}-accent`,72,132,64,5,C.green);
  if(subtitle)text(slide,`s${index}-subtitle`,72,154,1125,60,subtitle,24,C.gray);
  if(iconFile)icon(slide,iconFile,1162,63,48,48);
  line(slide,`s${index}-footer-rule`,72,660,1208,660,C.line,0.8);
  text(slide,`s${index}-confidential`,72,675,600,22,'NVIDIA Confidential',12,C.gray);
  text(slide,`s${index}-page`,1035,674,45,24,String(index).padStart(2,'0'),14,C.gray,false,'right');
  slide.images.add({path:`${ASSETS}/nvidia-template-image-1.png`,alt:'NVIDIA corporate logo',fit:'contain',position:{left:1100,top:668,width:115,height:40}});
}
function notes(slide,time,talk,{source=SRC.outline,draft=''}={}) {
  slide.speakerNotes.text=`SECTION 1 — INFERENCE FUNDAMENTALS\nSuggested time: ${time} minutes.\n\n${talk}\n${draft?`\nMOCKUP / PREPARATION: ${draft}\n`:''}\nSources: ${source}\nBrand assets: official NVIDIA Sans Corp Template LIGHT v2 and its bundled corporate icons. Diagrams are editable schematic illustrations; no benchmark measurements are depicted.`;
}
function dot(slide,name,x,y,r=7,color=C.green){return shape(slide,name,x-r,y-r,2*r,2*r,color,'none','ellipse');}
function header(slide,index,title,subtitle,iconFile,{keepChrome=false}={}) {
  if(!keepChrome)return base(slide,index,title,subtitle,iconFile);
  const get=name=>slide.shapes.items.find(s=>s.name===name);
  const titleShape=get(`s${index}-title`),subtitleShape=get(`s${index}-subtitle`);
  if(!titleShape||!subtitleShape)throw new Error(`Missing preserved header on slide ${index}`);
  titleShape.text=title;
  subtitleShape.text=subtitle;
}

const BUILDERS = {
  1(slide){
    base(slide,1,'The Coding Agent Loop','A program repeatedly sends context to an LLM server, then acts on its response.','coding.png');
    box(slide,'input',104,235,300,65,'Code + user request',{size:25,fill:C.soft});
    box(slide,'agent',104,348,300,112,'Agent program',{fill:C.white,stroke:C.black,size:32});
    box(slide,'server',806,264,350,234,'LLM server',{fill:C.black,color:C.white,size:38});
    text(slide,'server-http',835,425,290,35,'HTTP endpoint',23,C.green,false,'center');
    arrow(slide,'input-to-agent',254,300,254,348,C.gray);
    arrow(slide,'request-arrow',404,378,806,378,C.green,3);
    text(slide,'request-label',480,332,275,34,'Context',24,C.gray,false,'center');
    arrow(slide,'response-arrow',806,432,404,432,C.gray,3);
    text(slide,'response-label',470,453,285,34,'Response / tool call',24,C.gray,false,'center');
    box(slide,'tools',104,545,300,63,'Read · edit · run tests',{size:23,fill:C.soft});
    arrow(slide,'call-tools',184,460,184,545,C.gray);
    arrow(slide,'tool-results',329,545,329,460,C.teal);
    text(slide,'action-label',74,488,105,30,'Action',18,C.gray);
    text(slide,'result-label',343,489,115,30,'Result',18,C.teal);
    text(slide,'session-caption',528,532,610,90,'One agent session contains many inference requests.',27,C.black,true);
    notes(slide,1.5,'Open with the application, treating the LLM server as a black box. The agent program executes tools; the server returns text or a tool-call request. Tool results return to the agent program and become context for the next inference request. Do not introduce Dynamo yet.');
  },
  2(slide){
    base(slide,2,'Each Turn Sends More Context','The next inference request includes the conversation and the latest tool results.','document.png');
    const start=220,unit=148,gap=6,by=250,bh=72;
    for(const [row,y,parts] of [[1,by,['Code','User task']],[2,by+118,['Code','User task','Tool call','Tool result']],[3,by+236,['Code','User task','Tool call','Tool result','Next turn']]]){
      text(slide,`request-${row}`,72,y+8,130,52,`Request ${row}`,24,C.gray,true);
      parts.forEach((part,i)=>box(slide,`r${row}-context-${i}`,start+i*(unit+gap),y,unit,bh,part,{fill:i<2?C.soft:(i===parts.length-1&&row>1?'#DDEFE9':C.pale),size:23,bold:i<2}));
    }
    line(slide,'shared-prefix-bracket',220,600,522,600,C.green,4);
    text(slide,'shared-label',220,606,500,36,'The initial context is sent again.',23,C.gray);
    text(slide,'new-context-caption',752,601,435,44,'New text is appended at each turn.',23,C.teal);
    notes(slide,1.5,'Use an intentionally simplified append-only agent loop. Point to exactly the same code and task at the beginning of each request. Explain that real agents can manage or compact context, but that is outside this introductory example. The important distinction is one session versus many HTTP inference requests.');
  },
  3(slide){
    base(slide,3,'Inside a vLLM Server','The server processes requests using model weights and working state on the GPUs.','server-rack.png');
    text(slide,'client-label',75,330,160,80,'Agent\nprogram',28,C.black,true,'center');
    arrow(slide,'client-http',245,369,365,369,C.gray,3);
    text(slide,'http-label',249,321,110,34,'HTTP',21,C.gray,false,'center');
    shape(slide,'vllm-boundary',369,230,830,365,C.white,C.line);
    text(slide,'vllm-label',400,247,425,40,'vLLM server',29,C.black,true);
    box(slide,'endpoint',401,328,186,93,'HTTP\nendpoint',{fill:C.pale,size:25});
    arrow(slide,'endpoint-engine',589,369,658,369,C.gray);
    shape(slide,'gpu-region',662,302,506,260,C.pale);
    text(slide,'engine-label',687,317,452,43,'Inference engine · GPUs',29,C.black,true);
    box(slide,'weights',689,385,208,85,'Model weights',{fill:C.white,size:25});
    box(slide,'request-state',922,385,216,85,'Request state',{fill:C.soft,size:25});
    text(slide,'weight-detail',688,479,210,55,'Shared across\nrequests',21,C.gray,false,'center');
    text(slide,'state-detail',926,479,210,55,'Built from the\nrequest context',21,C.gray,false,'center');
    text(slide,'engine-init-caption',401,604,780,40,'The engine also has initialization and warm-up work.',24,C.gray);
    notes(slide,2,'Keep this entirely in the context of a standalone vLLM server. Weights are model parameters and are not request dependent. Request state is derived from the input context and used while generating. Mention initialized engine state only briefly; do not explain kernel or CUDA internals. The boxes are conceptual categories, not a literal GPU memory allocation map.');
  },
  4(slide){
    base(slide,4,'Prefill and Generation','Prefill processes the input. Generation produces new tokens using the accumulated state.','ml-inference.png');
    text(slide,'prompt-label',78,245,246,42,'Input context',26,C.gray,true);
    box(slide,'prompt',78,303,246,88,'Code + conversation',{fill:C.pale,size:24});
    arrow(slide,'prompt-prefill',324,347,393,347,C.gray);
    box(slide,'prefill',398,286,270,122,'Prefill',{fill:C.soft,size:35});
    arrow(slide,'prefill-state',533,409,533,485,C.green,3);
    box(slide,'working-state',405,487,256,70,'KV cache',{fill:C.soft,size:25});
    arrow(slide,'prefill-generation',669,347,756,347,C.gray);
    box(slide,'generation',762,286,414,122,'Generation (decode)',{fill:'#DDEFE9',size:29});
    text(slide,'generation-loop',785,427,315,70,'Produce a token.\nUse and update the state.',24,C.teal,false,'center');
    line(slide,'state-generation-path',661,521,1140,521,C.teal,2.5);
    arrow(slide,'state-generation-up',1140,521,1140,408,C.teal,2.5);
    text(slide,'output-tokens',783,551,390,52,'token → token → token → …',28,C.black,true,'center');
    text(slide,'state-abstraction',78,599,1095,41,'We use “KV cache” as the working-state abstraction for this workshop.',23,C.gray);
    notes(slide,2,'Explain only the two phases and the working-state abstraction. Prefill processes input context; generation consumes and updates accumulated state. Do not distinguish quadratic attention KV tensors from Mamba or other recurrent state. The arrows are a conceptual dependency diagram, not scheduling or memory-manager internals.');
  },
  5(slide,options={}){
    header(slide,5,'Reuse the KV Cache of a Shared Prefix','The agent resends the text. The server reuses its KV cache for the matching prefix.','workflow.png',options);
    const start=220,unit=148,gap=6,bh=64;
    for(const [row,y,parts] of [[1,249,['Code','User task']],[2,359,['Code','User task','Tool call','Tool result']]]){
      text(slide,`reuse-request-${row}`,72,y+6,130,52,`Request ${row}`,24,C.gray,true);
      parts.forEach((part,i)=>box(slide,`reuse-r${row}-context-${i}`,start+i*(unit+gap),y,unit,bh,part,{fill:i<2?C.soft:(i===3?'#DDEFE9':C.pale),size:23,bold:i<2}));
    }
    text(slide,'first-request-effect',875,242,315,76,'Request 1 builds\nthe server’s KV cache.',24,C.gray);
    text(slide,'second-request-effect',875,352,315,76,'Request 2 still sends\nall of the text.',24,C.gray);
    shape(slide,'reuse-server-boundary',190,460,1018,176,C.white,C.line).sendToBack();
    text(slide,'reuse-server-label',899,476,285,45,'vLLM server',28,C.black,true);
    text(slide,'cache-location',899,529,285,42,'KV cache lives here.',23,C.gray);
    arrow(slide,'matched-prefix-to-cache',371,424,371,523,C.green,3);
    arrow(slide,'new-context-to-prefill',679,424,679,523,C.teal,3);
    box(slide,'server-kv-cache',220,523,302,59,'KV cache',{fill:C.soft,size:27});
    box(slide,'new-context-prefill',528,523,302,59,'Prefill new context',{fill:'#DDEFE9',size:25});
    text(slide,'cached-prefix-action',220,587,302,35,'Reuse cached prefix state',21,C.teal,true,'center');
    text(slide,'suffix-action',528,587,302,35,'Compute the new suffix',21,C.gray,false,'center');
    notes(slide,1.5,'Continue the visual language of slide 2: identical Code and User task blocks are sent again, followed by the Tool call and Tool result. The first request builds KV cache inside the vLLM server. For the next request the engine reuses the KV cache associated with the matching prefix and computes the new suffix. The reused object is server-side KV cache, not the text in the HTTP payload. Generation is still required. This remains a visual explanation, without a separate live prefix-reuse experiment. The following slide explains the cost of recomputation.',{source:`${SRC.outline}\n${SRC.cache}`});
  },
  6(slide){
    base(slide,6,'Cached State Changes the Cost of a Request','The full context still arrives with the request. The server may already have processed part of it.','accuracy.png');
    text(slide,'available-heading',80,255,500,52,'Cache available',32,C.teal,true);
    text(slide,'absent-heading',710,255,500,52,'Cache absent',32,C.black,true);
    box(slide,'same-request-left',80,336,440,66,'Code + conversation + new turn',{fill:C.pale,size:24});
    box(slide,'same-request-right',710,336,440,66,'Code + conversation + new turn',{fill:C.pale,size:24});
    arrow(slide,'cache-hit-down',300,403,300,452,C.green);
    arrow(slide,'cache-miss-down',930,403,930,452,C.gray);
    text(slide,'reuse-outcome',80,460,440,82,'Reuse prior computation.\nProcess the new context.',28,C.teal,true);
    text(slide,'recompute-outcome',710,460,440,82,'Recompute the context.\nSpend additional GPU work.',28,C.black,true);
    line(slide,'comparison-separator',630,261,630,550,C.line,1);
    text(slide,'recompute-caveat',80,580,1110,60,'Cached state can be rebuilt. Rebuilding costs time and serving capacity.',29,C.black,true);
    notes(slide,1.5,'Statefulness is the operational teaching point. Retained computation affects placement, cost, latency, and available capacity. Conversation history stays with the agent and is sent in the request; derived server cache can be recomputed if lost. This is not a promise that every in-flight generation or arbitrary engine state can be reconstructed without another mechanism. No need to introduce routing or KVCR yet.',{source:`${SRC.outline}\n${SRC.cache}`});
  },
  7(slide){
    base(slide,7,'A Dynamo-Managed Service','Separate the HTTP entry point from the inference engine running on the GPUs.','config-sdk.png');
    text(slide,'agent-label',76,357,160,75,'Agent\nprogram',28,C.black,true,'center');
    arrow(slide,'agent-service',241,394,392,394,C.gray,3);
    text(slide,'public-http',250,345,120,32,'HTTP',22,C.gray,false,'center');
    shape(slide,'k8s-namespace',362,256,838,320,C.white,C.line).sendToBack();
    text(slide,'namespace-caption',388,270,640,35,'Kubernetes · Dynamo-managed deployment',23,C.gray);
    box(slide,'dynamo-frontend',392,352,275,116,'Dynamo frontend',{fill:C.soft,size:29});
    text(slide,'frontend-cpu',394,490,275,36,'CPU · HTTP endpoint',23,C.gray,false,'center');
    arrow(slide,'frontend-worker',671,410,786,410,C.gray,3);
    box(slide,'dynamo-worker',790,352,370,116,'vLLM worker',{fill:C.pale,size:32});
    text(slide,'worker-gpu',791,490,369,36,'GPUs · model and request state',23,C.gray,false,'center');
    text(slide,'replica-scope',76,601,1100,42,'Begin with one worker replica. We will change the deployment as demand grows.',26,C.black);
    notes(slide,2,'This is the first introduction of Dynamo. Keep the frontend/worker separation concrete and defer its broader reasons. One worker replica can use multiple GPUs; the target remains Super VL. Explain that the diagram shows the serving data path, not a complete list of control-plane and discovery infrastructure. No disaggregation yet.');
  },
  8(slide){
    base(slide,8,'Describe the Service With a DGD','The Dynamo operator reconciles the desired service into Kubernetes resources.','tools.png');
    const yaml=`apiVersion: nvidia.com/v1beta1\nkind: DynamoGraphDeployment\nmetadata:\n  name: coding-agent\nspec:\n  backendFramework: vllm\n  components:\n  - name: Frontend\n    type: frontend\n    replicas: 1\n  - name: Worker\n    type: worker\n    replicas: 1`;
    shape(slide,'yaml-background',72,236,650,380,'#F4F4F4');
    const code=text(slide,'yaml-code',94,249,606,353,yaml,20,C.black,false,'left','Courier New');
    code.text.verticalAlignment='top';
    text(slide,'excerpt-label',72,619,700,28,'DGD excerpt · pod templates and runtime settings omitted',18,C.gray);
    box(slide,'desired-state',839,244,334,69,'Desired state',{fill:C.soft,size:26});
    arrow(slide,'desired-to-operator',1006,313,1006,355,C.gray);
    box(slide,'operator',839,359,334,76,'Dynamo operator',{fill:C.white,stroke:C.green,size:28});
    arrow(slide,'operator-to-resources',1006,435,1006,480,C.gray);
    box(slide,'resources',839,484,334,110,'Services · Pods\nFrontend + worker',{fill:C.pale,size:26});
    notes(slide,2,'Walk through the actual minimal manifest in the live demo. This slide contains an editable, deliberately incomplete excerpt using the repository schema. It is not a complete apply-ready YAML. The exact final barebones Super VL DGD is still a preparation item. Image digests, model revision, GPU/DRA allocation, command arguments, storage, and discovery prerequisites belong in that full manifest. Show operator reconciliation and the resources that appear.',{source:`${SRC.outline}\n${SRC.dgd}`,draft:'Replace the excerpt with the chosen final demo manifest or keep it as an explanatory excerpt alongside the real file.'});
  },
  9(slide,options={}){
    header(slide,9,'Startup Time Breakdown','From DGD submission to the first successful response.','download-sync.png',options);
    text(slide,'waterfall-axis-label',440,220,400,35,'Elapsed time →',23,C.gray);
    text(slide,'waterfall-pending',950,220,250,35,'Timing pending',22,C.gray,false,'right');
    line(slide,'waterfall-origin',416,266,416,566,C.line,1);
    const phases=['Scheduling','Image / container startup','Weight loading','Engine init + warm-up','Ready / first response'];
    phases.forEach((label,i)=>{
      const x=440+i*145,y=276+i*64;
      text(slide,`waterfall-phase-${i}`,80,y-10,310,52,label,24,C.black,i===2||i===3);
      const fill=i===2?C.soft:(i===3?'#DDEFE9':C.pale);
      const bar=shape(slide,`waterfall-placeholder-${i}`,x,y,126,34,fill,C.line);
      bar.line={fill:i===2?C.green:C.line,width:1.5,style:'dashed'};
      text(slide,`waterfall-value-${i}`,x,y,126,34,'TBD',21,C.gray,false,'center');
      if(i<phases.length-1){line(slide,`waterfall-drop-${i}`,x+126,y+17,x+126,y+81,C.line,1.5,true);line(slide,`waterfall-join-${i}`,x+126,y+81,x+145,y+81,C.line,1.5,true);}
    });
    arrow(slide,'deployment-to-serving-span',440,590,1146,590,C.black,2);
    text(slide,'deployment-to-serving-label',440,597,740,42,'Deployment-to-serving time',27,C.black,true);
    text(slide,'waterfall-placeholder-note',80,636,1120,22,'Layout mockup: phase offsets and bar widths will be replaced by measured timings.',17,C.gray);
    notes(slide,2,'Use a startup waterfall populated by the measured start offset and duration of each phase. Current equal-width dashed bars, their offsets, and the TBD labels are layout placeholders, not estimated or measured durations. Replace them together once actual Super VL timing is available. Keep scheduling, image/container startup, weight loading, engine initialization/warm-up, and readiness/first-response evidence distinguishable. If measured phases overlap, preserve the overlap instead of forcing a serial sum. Measure the full submission-to-first-success interval independently. Introduce ModelExpress later in scaling.',{draft:'Actual Super VL phase start/end timestamps are pending. The current waterfall has no numeric time scale or performance results.'});
  },
  10(slide){
    base(slide,10,'Replay the Coding-Agent Workload','Use a controlled agentic trace to establish the serving baseline.','comm-chat.png');
    box(slide,'trace',80,291,276,110,'Agentic trace',{fill:C.pale,size:32});
    arrow(slide,'trace-to-aiperf',356,346,459,346,C.gray,3);
    box(slide,'aiperf',464,291,290,110,'AIPerf',{fill:C.soft,size:37});
    arrow(slide,'aiperf-to-service',754,346,857,346,C.gray,3);
    box(slide,'service',862,291,336,110,'Dynamo service',{fill:C.pale,size:31});
    text(slide,'trace-desc',80,428,276,87,'Requests, context,\nand session structure',24,C.gray,false,'center');
    text(slide,'load-desc',465,428,289,87,'Send requests.\nMeasure responses.',24,C.gray,false,'center');
    text(slide,'service-desc',862,428,336,87,'One frontend.\nOne worker replica.',24,C.gray,false,'center');
    text(slide,'workload-constant',80,571,1110,68,'Keep the workload fixed. Later, increase the offered load.',30,C.black,true);
    notes(slide,1,'Introduce AIPerf as the controlled measurement mechanism. The exact agent and trace are intentionally deferred. Use a low enough baseline load to explain measurements; the traffic ramp belongs in section 2. The replay fixture must state which session dependencies and timing semantics it preserves. Do not imply that any arbitrary trace format is immediately supported.',{source:`${SRC.outline}\n${SRC.metrics}`,draft:'Insert the final trace identity and runnable AIPerf command in the speaker notes once chosen.'});
  },
  11(slide){
    base(slide,11,'Latency From the Agent’s Perspective','Measure when the response begins, how quickly it arrives, and when it finishes.','gpu.png');
    const y=315,start=112,first=493,end=1140;
    line(slide,'request-timeline',start,y,end,y,C.line,3);
    dot(slide,'request-start',start,y,8,C.black);
    const tokenXs=[first,594,684,793,901,1004,end];
    tokenXs.forEach((x,i)=>shape(slide,`token-${i}`,x-8,y-17,16,34,C.green));
    text(slide,'request-sent-label',80,246,210,44,'Request sent',25,C.black,true);
    text(slide,'first-token-label',first-45,246,190,44,'First token',25,C.black,true);
    text(slide,'last-token-label',end-110,246,210,44,'Last token',25,C.black,true,'right');
    arrow(slide,'ttft-span',start,401,first,401,C.gray,2);
    text(slide,'ttft-label',start,417,405,80,'Time to first token\nWait before the answer starts',26,C.black,true);
    arrow(slide,'token-gap',684,355,793,355,C.teal,2);
    text(slide,'generation-speed-label',630,417,545,80,'Inter-token latency / generation speed\nThe cadence of the streamed answer',26,C.teal,true);
    arrow(slide,'end-to-end-span',start,557,end,557,C.black,2);
    text(slide,'e2e-label',start,574,990,52,'End-to-end latency: request sent → response complete',28,C.black,true);
    notes(slide,1.5,'Explain client-observed measurements. Time to first token includes all work and waiting before the first token arrives; it is not a pure prefill timer. Generation speed and inter-token latency describe streaming behavior, but their precise aggregation definitions must match the chosen AIPerf report. Do not present them as exact reciprocals in every reporting mode. Token positions are illustrative and are not benchmark data.',{source:`${SRC.outline}\n${SRC.metrics}`});
  },
  12(slide,options={}){
    header(slide,12,'System Throughput and User Interactivity','Two different rates: GPU efficiency and the speed of one user’s streamed answer.','scalability-up.png',options);
    text(slide,'system-throughput-heading',80,247,490,54,'System throughput',32,C.black,true);
    text(slide,'user-throughput-heading',710,247,490,54,'User throughput',32,C.black,true);
    text(slide,'system-throughput-unit',80,311,490,75,'tok/s/GPU',51,C.teal,true);
    text(slide,'user-throughput-unit',710,311,490,75,'tok/s/user',51,C.teal,true);
    text(slide,'system-throughput-meaning',80,402,495,92,'Aggregate output rate\nper allocated GPU.',29,C.black,true);
    text(slide,'user-throughput-meaning',710,402,490,92,'Generation speed for\none active user / request.',29,C.black,true);
    text(slide,'system-throughput-denominator',80,500,495,48,'Service output tok/s ÷ GPU count',24,C.gray);
    text(slide,'user-throughput-definition',710,500,490,48,'Interactivity · excludes TTFT',24,C.gray);
    line(slide,'throughput-separator',635,256,635,548,C.line,1);
    text(slide,'supporting-service-metrics',80,565,1120,42,'Also track TTFT, request latency, request throughput, percentiles, and errors.',23,C.gray);
    text(slide,'throughput-takeaway',80,610,1120,42,'Report both: GPU efficiency and user interactivity.',29,C.black,true);
    notes(slide,1.5,'Show both rates explicitly. System throughput is the aggregate service output-token rate over the measurement window, normalized by allocated serving GPUs; record that GPU count alongside the result. AIPerf Output Token Throughput Per User is a per-request generation-rate metric computed as 1 / ITL in seconds and excludes TTFT. Its percentiles describe individual request interactivity, not fleet throughput or the completion rate of whole agent tasks. Report TTFT and end-to-end request latency separately. Avoid deriving per-user rate by dividing aggregate throughput by configured concurrency. Report errors, request throughput, and chosen latency/rate percentiles as well. Hand off to scaling by asking what happens when more coding agents arrive.',{source:`${SRC.outline}\n${SRC.metricDefinitions}`,draft:'Insert the real AIPerf baseline later, with the chosen per-user metric definition, GPU count, workload identity, and percentiles. No numerical benchmark results are depicted.'});
  },
};

export const plan = [
  [1,'The Coding Agent Loop',1.5,'diagram'],[2,'Each Turn Sends More Context',1.5,'context rows'],
  [3,'Inside a vLLM Server',2,'architecture'],[4,'Prefill and Generation',2,'flow'],
  [5,'Reuse the KV Cache of a Shared Prefix',1.5,'request rows and server-side cache'],[6,'Cached State Changes the Cost of a Request',1.5,'comparison'],
  [7,'A Dynamo-Managed Service',2,'architecture'],[8,'Describe the Service With a DGD',2,'code and reconciliation'],
  [9,'Startup Time Breakdown',2,'waterfall mockup'],[10,'Replay the Coding-Agent Workload',1,'flow'],
  [11,'Latency From the Agent’s Perspective',1.5,'annotated timeline'],[12,'System Throughput and User Interactivity',1.5,'side-by-side metric definitions'],
];

export async function buildSection1({presentation,input={}}) {
  presentation.theme.defaultFont=FONT;
  presentation.theme.colorScheme={name:'NVIDIA Light',themeColors:{accent1:C.green,accent2:C.teal,accent3:C.blue,accent4:'#5D1682',accent5:'#890C58',accent6:C.mid,bg1:C.white,bg2:C.pale,tx1:C.black,tx2:C.gray,dk1:'#000000',dk2:C.gray,lt1:C.white,lt2:'#CDCDCD',hlink:C.blue,folHlink:'#5D1682'}};
  const created=[];
  for(const index of input.indexes??[1]){
    const firstBlank=index===1&&presentation.slides.items.length===1&&presentation.slides.getItem(0).shapes.items.length===0;
    if(!firstBlank&&presentation.slides.items.length!==index-1)throw new Error(`Slide ${index} is not the next empty slot. Edit the existing live slide instead of rebuilding it.`);
    const slide=index===1&&presentation.slides.items.length===1?presentation.slides.getItem(0):presentation.slides.add({width:1280,height:720});
    BUILDERS[index](slide);
    created.push({number:index,title:plan.find(x=>x[0]===index)[1],id:slide.toSnapshot().aid});
  }
  return {created,totalSlides:presentation.slides.items.length,plannedMinutes:plan.reduce((sum,x)=>sum+x[2],0)};
}

// Rebuild only the commented slide bodies, preserving slide IDs, comments,
// title/footer objects, original corporate images, and all other slides.
export async function reviseCommentedSlides({presentation,input={}}) {
  const revised=[];
  for(const index of input.indexes??[5,9,12]){
    if(![5,9,12].includes(index))throw new Error(`Slide ${index} is outside this revision`);
    const slide=presentation.slides.getItem(index-1);
    const bodyIds=slide.shapes.items.filter(s=>!s.name?.startsWith(`s${index}-`)).map(s=>s.toSnapshot().aid);
    presentation.delete(bodyIds);
    BUILDERS[index](slide,{keepChrome:true});
    revised.push({number:index,id:slide.toSnapshot().aid,title:plan.find(x=>x[0]===index)[1]});
  }
  if((input.indexes??[5,9,12]).includes(5)){
    const stateLabel=presentation.slides.getItem(3).shapes.items.find(s=>s.name==='working-state-label');
    if(stateLabel)stateLabel.text='KV cache';
  }
  return {revised,totalSlides:presentation.slides.items.length,plannedMinutes:plan.reduce((sum,x)=>sum+x[2],0)};
}
