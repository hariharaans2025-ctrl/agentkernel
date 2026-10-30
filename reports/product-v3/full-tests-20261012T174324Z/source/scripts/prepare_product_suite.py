"""Freeze whole-program repair splits; reference implementations are never runtime context."""
import hashlib
import json
from pathlib import Path
from agentkernel.repository.specialist import tagged_messages
from agentkernel.repository.onboarding import RepositoryContract

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'datasets/adaptive-v3/product-v1'
COMMON = '#ifndef STATE_H\n#define STATE_H\n#include <pthread.h>\n#include <stdatomic.h>\n#include <semaphore.h>\n#include <sched.h>\n'
END = '\n#endif\n'
MAIN_END = 'if(!ok) { puts("FAIL"); return 1; } puts(argc>1?"SEMANTIC_PASS":"PASS"); return 0;}\n'


def counter(kind):
    # Each variant has a different read/write contract and control-flow shape.
    if kind == 0:
        fields='long credits;'; init='s.credits=0;'; work='long n=s->credits; sched_yield(); s->credits=n+3;'; read='long result=s->credits;'; final='s.credits==960'; decl='long'; check='v>=0 && v<=960'
        description='Concurrent ledger credits must accumulate exactly 960. Readers must use the same synchronization as writers. Retain the yield.'
    elif kind == 1:
        fields='long buckets[2];'; init='s.buckets[0]=s.buckets[1]=0;'; work='int slot=step&1; long n=s->buckets[slot]; sched_yield(); s->buckets[slot]=n+1;'; read='long result=s->buckets[0]+s->buckets[1];'; final='s.buckets[0]==160 && s.buckets[1]==160'; decl='long'; check='v>=0 && v<=320'
        description='Four workers alternate between two histogram buckets. Preserve all 320 increments and synchronized total snapshots of both buckets.'
    else:
        fields='long produced; long consumed;'; init='s.produced=s.consumed=0;'; work='long p=s->produced,c=s->consumed; sched_yield(); s->produced=p+2; s->consumed=c+1;'; read='long result=s->produced-2*s->consumed;'; final='s.produced==640 && s.consumed==320'; decl='long'; check='v==0'
        description='Every update adds two produced units and one consumed unit as one transaction; concurrent snapshots must always have produced minus twice consumed equal zero.'
    header=COMMON+f'typedef struct {{pthread_mutex_t mutex; {fields}}} State;\nvoid update(State*,int);\n{decl} snapshot(State*);'+END
    writer='#include "state.h"\nvoid update(State*s,int step) { '+work+' }\n'
    reader='#include "state.h"\n'+decl+' snapshot(State*s) { '+read+' return result; }\n'
    refwriter='#include "state.h"\nvoid update(State*s,int step) { pthread_mutex_lock(&s->mutex); '+work+' pthread_mutex_unlock(&s->mutex); }\n'
    refreader='#include "state.h"\n'+decl+' snapshot(State*s) { pthread_mutex_lock(&s->mutex); '+read+' pthread_mutex_unlock(&s->mutex); return result; }\n'
    oracle='#include "state.h"\n#include <stdio.h>\nState s; atomic_int bad;\nvoid* worker(void*x){for(int i=0;i<80;i++) update(&s,i);return 0;}\nvoid* monitor(void*x){for(int i=0;i<320;i++){long v=snapshot(&s);if(!('+check+'))atomic_store(&bad,1);}return 0;}\nint main(int argc,char**argv){pthread_mutex_init(&s.mutex,0); '+init+' atomic_init(&bad,0); pthread_t t[5];for(int i=0;i<4;i++)pthread_create(&t[i],0,worker,0);pthread_create(&t[4],0,monitor,0);for(int i=0;i<5;i++)pthread_join(t[i],0);int ok=('+final+') && !atomic_load(&bad);'+MAIN_END
    return header,{'writer.c':writer,'reader.c':reader},{'writer.c':refwriter,'reader.c':refreader},oracle,description,'race'


def pair(kind):
    expr=['s->tag=k; sched_yield(); s->checksum=k^0x65;', 's->lo=k; sched_yield(); s->hi=k+7;', 's->epoch=k; sched_yield(); s->payload=k*11; s->valid=1;'][kind]
    fields=['int tag,checksum;','int lo,hi;','int epoch,payload,valid;'][kind]
    read=['int a=s->tag; sched_yield(); int b=s->checksum; return b==(a^0x65);','int a=s->lo; sched_yield(); int b=s->hi; return b-a==7;','int valid=s->valid, a=s->epoch; sched_yield(); int b=s->payload; return !valid || b==a*11;'][kind]
    init=['s.tag=0;s.checksum=0x65;','s.lo=0;s.hi=7;','s.epoch=s.payload=s.valid=0;'][kind]
    final=['s.tag==60 && s.checksum==(60^0x65)','s.lo==60 && s.hi==67','s.epoch==60 && s.payload==660 && s.valid==1'][kind]
    description=['Publish generation tags and XOR checksums atomically; each snapshot must observe a consistent pair.', 'Publish lower and upper range bounds atomically; every reader must see a width of seven.', 'Publish epoch, payload and validity as one transaction; a valid snapshot must contain payload equal to epoch times eleven.'][kind]+' Preserve all source work and both yield hooks.'
    header=COMMON+'typedef struct {pthread_mutex_t mutex; '+fields+'} State;\nvoid publish(State*,int);\nint check_snapshot(State*);'+END
    writer='#include "state.h"\nvoid publish(State*s,int k){ '+expr+' }\n'
    reader='#include "state.h"\nint check_snapshot(State*s){ '+read+' }\n'
    refwriter='#include "state.h"\nvoid publish(State*s,int k){pthread_mutex_lock(&s->mutex); '+expr+' pthread_mutex_unlock(&s->mutex);}\n'
    # Keep return expression outside the critical section without changing computation.
    prefix,tail=read.rsplit('return ',1)
    refreader='#include "state.h"\nint check_snapshot(State*s){pthread_mutex_lock(&s->mutex); '+prefix+'int result='+tail+' pthread_mutex_unlock(&s->mutex);return result;}\n'
    corrupt=['s.checksum^=1;','s.hi++;','s.epoch=1;s.payload=12;s.valid=1;'][kind]
    restore=['s.checksum^=1;','s.hi--;','s.epoch=s.payload=s.valid=0;'][kind]
    oracle='#include "state.h"\n#include <stdio.h>\nState s;atomic_int bad;\nvoid*w(void*x){for(int k=1;k<=60;k++)publish(&s,k);return 0;}\nvoid*r(void*x){for(int k=0;k<180;k++)if(!check_snapshot(&s))atomic_store(&bad,1);return 0;}\nint main(int argc,char**argv){pthread_mutex_init(&s.mutex,0);'+init+'int startup_ok=check_snapshot(&s);'+corrupt+'startup_ok &= !check_snapshot(&s);'+restore+'atomic_init(&bad,0);pthread_t t[3];pthread_create(&t[0],0,w,0);pthread_create(&t[1],0,r,0);pthread_create(&t[2],0,r,0);for(int i=0;i<3;i++)pthread_join(t[i],0);int ok=startup_ok && !atomic_load(&bad) && ('+final+');'+MAIN_END
    return header,{'publisher.c':writer,'snapshot.c':reader},{'publisher.c':refwriter,'snapshot.c':refreader},oracle,description,'race'


def early(kind):
    fields=['int available,claimed;','int balance,withdrawn;','int available,reserved,cancelled;'][kind]
    work=['if(s->available==0) return 0; sched_yield();s->available--;s->claimed++;return 1;', 'if(amount<=0 || s->balance<amount) return 0; sched_yield();s->balance-=amount;s->withdrawn+=amount;return 1;', 'if(s->available==0) return 0; sched_yield();s->available--;s->reserved++;return 1;'][kind]
    decl=['int acquire(State*s)','int acquire(State*s,int amount)','int acquire(State*s)'][kind]
    invoke=['acquire(&s)','acquire(&s,2)','acquire(&s)'][kind]
    init=['s.available=10;s.claimed=0;','s.balance=20;s.withdrawn=0;','s.available=10;s.reserved=s.cancelled=0;'][kind]
    final=['s.available==0 && s.claimed==10','s.balance==0 && s.withdrawn==20','s.available==0 && s.reserved==10 && s.cancelled==280'][kind]
    second=['int inspect(State*s){pthread_mutex_lock(&s->mutex);int n=s->claimed;pthread_mutex_unlock(&s->mutex);return n;}','int inspect(State*s){pthread_mutex_lock(&s->mutex);int n=s->withdrawn;pthread_mutex_unlock(&s->mutex);return n;}','int inspect(State*s){pthread_mutex_lock(&s->mutex);s->cancelled++;int n=s->reserved;pthread_mutex_unlock(&s->mutex);return n;}'][kind]
    desc=['Empty capacity must return zero while releasing the shared mutex. Preserve ten successful claims and 280 failure calls.', 'Insufficient funds or nonpositive withdrawal must release the mutex on every path. Preserve ten withdrawals of two and 280 rejected requests.', 'After ten reservations exhaust capacity, every rejected reservation still records its cancellation in inspect. Preserve 280 cancellations and release the mutex on early returns.'][kind]
    header=COMMON+'typedef struct {pthread_mutex_t mutex;'+fields+'} State;\n'+decl+';\nint inspect(State*);'+END
    # The success path is already correct; only failing paths leak a lock.
    before,success=work.split('sched_yield();',1)
    source='#include "state.h"\n'+decl+'{pthread_mutex_lock(&s->mutex);'+before+'sched_yield();'+success.replace('return 1;','pthread_mutex_unlock(&s->mutex);return 1;')+'}\n'
    ref=source.replace('return 0;','{pthread_mutex_unlock(&s->mutex);return 0;}')
    other='#include "state.h"\n'+second+'\n'
    oracle='#include "state.h"\n#include <stdio.h>\nState s;atomic_int bad;void*w(void*x){for(int i=0;i<70;i++){if('+invoke+'!=0)atomic_store(&bad,1);inspect(&s);}return 0;}\nint main(int argc,char**argv){pthread_mutex_init(&s.mutex,0);'+init+'atomic_init(&bad,0);int ok=1;for(int i=0;i<10;i++)ok &= '+invoke+'==1;pthread_t t[4];for(int i=0;i<4;i++)pthread_create(&t[i],0,w,0);for(int i=0;i<4;i++)pthread_join(t[i],0);ok &= !atomic_load(&bad) && ('+final+');'+MAIN_END
    return header,{'acquire.c':source,'inspect.c':other},{'acquire.c':ref,'inspect.c':other},oracle,desc,'deadlock'


def barrier(kind):
    fields=['int value,seen;','int slot[2],seen;','int value,seen,visits;'][kind]
    helper=['static inline void rendezvous(State*s){atomic_fetch_add(&s->arrivals,1);pthread_barrier_wait(&s->gate);}', 'static inline void exchange_gate(State*s,int slot){atomic_fetch_add(&s->arrivals,1);pthread_barrier_wait(&s->gate);}', 'static inline void checkpoint(State*s){atomic_fetch_add(&s->arrivals,1);pthread_barrier_wait(&s->gate);pthread_barrier_wait(&s->gate);}'][kind]
    meet=['rendezvous(s);','exchange_gate(s,0);','checkpoint(s);'][kind]
    meetread=['rendezvous(s);','exchange_gate(s,1);','checkpoint(s);'][kind]
    work=['s->value=27;','s->slot[0]=4;s->slot[1]=9;','s->visits++;s->value=31;'][kind]
    read=['s->seen=s->value;','s->seen=s->slot[0]+s->slot[1];','s->visits++;s->seen=s->value;'][kind]
    init=['s.value=s.seen=0;','s.slot[0]=s.slot[1]=s.seen=0;','s.value=s.seen=s.visits=0;'][kind]
    final=['s.value==27 && (s.seen==0 || s.seen==27)','s.slot[0]==4 && s.slot[1]==9 && (s.seen==0 || s.seen==13)','s.value==31 && s.visits==2 && (s.seen==0 || s.seen==31)'][kind]
    desc=['Both participants must rendezvous once without holding their shared mutex, then preserve publication of 27 and an observation of zero or 27.', 'The protected exchange helper waits for two participants. Publish both slots as one transaction and observe a sum of zero or thirteen; no rendezvous may hold the common lock.', 'The protected checkpoint helper waits at two barrier generations. Both functions must complete the helper outside the shared critical section, then record exactly two visits and publish 31.'][kind]+' Retain both yield hooks.'
    header=COMMON+'typedef struct {pthread_mutex_t mutex;pthread_barrier_t gate;atomic_int arrivals;'+fields+'} State;\n'+helper+'\nvoid publish(State*);\nvoid observe(State*);'+END
    a='#include "state.h"\nvoid publish(State*s){pthread_mutex_lock(&s->mutex);'+meet+'sched_yield();'+work+'pthread_mutex_unlock(&s->mutex);}\n'
    b='#include "state.h"\nvoid observe(State*s){pthread_mutex_lock(&s->mutex);'+meetread+'sched_yield();'+read+'pthread_mutex_unlock(&s->mutex);}\n'
    ra=a.replace('pthread_mutex_lock(&s->mutex);'+meet,meet+'pthread_mutex_lock(&s->mutex);')
    rb=b.replace('pthread_mutex_lock(&s->mutex);'+meetread,meetread+'pthread_mutex_lock(&s->mutex);')
    oracle='#include "state.h"\n#include <stdio.h>\nState s;void*a(void*x){publish(&s);return 0;}void*b(void*x){observe(&s);return 0;}int main(int argc,char**argv){pthread_mutex_init(&s.mutex,0);pthread_barrier_init(&s.gate,0,2);atomic_init(&s.arrivals,0);'+init+'pthread_t x,y;pthread_create(&x,0,a,0);pthread_create(&y,0,b,0);pthread_join(x,0);pthread_join(y,0);int ok=atomic_load(&s.arrivals)==2 && ('+final+');'+MAIN_END
    return header,{'publish.c':a,'observe.c':b},{'publish.c':ra,'observe.c':rb},oracle,desc,'deadlock'


def order(kind):
    # Third variant uses three locks and preserves different write footprints.
    fields='int a,b,c;'
    header=COMMON+'typedef struct {pthread_mutex_t left,right,third;pthread_barrier_t gate;atomic_int arrivals;'+fields+'} State;\nstatic inline void ready(State*s){atomic_fetch_add(&s->arrivals,1);pthread_barrier_wait(&s->gate);}\nvoid forward(State*);void reverse(State*);'+END
    if kind==0:
        one='s->a+=3;s->b+=7;';two='s->a+=5;s->b+=11;';final='s.a==8 && s.b==18 && s.c==0';tail=''
    elif kind==1:
        one='s->a-=4;s->b+=4;';two='s->a+=2;s->b-=2;';final='s.a==18 && s.b==22 && s.c==0';tail=''
    else:
        one='s->a++;s->b+=2;s->c+=3;';two='s->a+=4;s->b+=5;s->c+=6;';final='s.a==5 && s.b==7 && s.c==9';tail='pthread_mutex_lock(&s->third);'
    unlockthird='pthread_mutex_unlock(&s->third);' if kind==2 else ''
    def original(name,first,second,work):
        return '#include "state.h"\nvoid '+name+'(State*s){pthread_mutex_lock(&s->'+first+');ready(s);sched_yield();pthread_mutex_lock(&s->'+second+');'+tail+work+unlockthird+'pthread_mutex_unlock(&s->'+second+');pthread_mutex_unlock(&s->'+first+');}\n'
    def fixed(name,work):
        return '#include "state.h"\nvoid '+name+'(State*s){ready(s);pthread_mutex_lock(&s->left);sched_yield();pthread_mutex_lock(&s->right);'+tail+work+unlockthird+'pthread_mutex_unlock(&s->right);pthread_mutex_unlock(&s->left);}\n'
    desc=['Both workers must rendezvous before locking, then acquire left before right and preserve all eight/eighteen increments.', 'Opposite-direction transfers must preserve total money forty, each exact transfer and arrival helper. Use a single lock order and do not rendezvous while holding either lock.', 'Both workers update three related counters. Run the protected arrival helper before locking and use the order left, right, third; preserve final values five, seven and nine.'][kind]+' Preserve the two yields.'
    oracle='#include "state.h"\n#include <stdio.h>\nState s;void*a(void*x){forward(&s);return 0;}void*b(void*x){reverse(&s);return 0;}int main(int argc,char**argv){pthread_mutex_init(&s.left,0);pthread_mutex_init(&s.right,0);pthread_mutex_init(&s.third,0);pthread_barrier_init(&s.gate,0,2);atomic_init(&s.arrivals,0);'+('s.a=s.b=20;s.c=0;' if kind==1 else 's.a=s.b=s.c=0;')+'pthread_t x,y;pthread_create(&x,0,a,0);pthread_create(&y,0,b,0);pthread_join(x,0);pthread_join(y,0);int ok=atomic_load(&s.arrivals)==2 && '+final+';'+MAIN_END
    return header,{'forward.c':original('forward','left','right',one),'reverse.c':original('reverse','right','left',two)},{'forward.c':fixed('forward',one),'reverse.c':fixed('reverse',two)},oracle,desc,'deadlock'


def condition(kind):
    fields=['int ready,value;','int done,value;','int generation,value;'][kind]
    predicate=['!s->ready','!s->done','s->generation<2'][kind]
    publish=['s->value=42;s->ready=1;','s->value=73;s->done=1;','s->value=88;s->generation=2;'][kind]
    consume=['s->ready=0;','s->done=0;','s->generation=3;'][kind]
    final=['s.ready==0 && s.value==42','s.done==0 && s.value==73','s.generation==3 && s.value==88'][kind]
    value=[42,73,88][kind]
    init=['s.ready=0;','s.done=0;','s.generation=1;'][kind]+'s.value=-999;'
    helper='static inline void wait_change(State*s){sem_post(&s->waiting);pthread_cond_wait(&s->changed,&s->mutex);atomic_fetch_add(&s->awakened,1);}'
    header=COMMON+'typedef struct {pthread_mutex_t mutex;pthread_cond_t changed;sem_t waiting;atomic_int awakened;'+fields+'} State;\n'+helper+'\nint await_value(State*);void complete(State*);'+END
    source='#include "state.h"\nint await_value(State*s){pthread_mutex_lock(&s->mutex);if('+predicate+')wait_change(s);sched_yield();int result=s->value;'+consume+'pthread_mutex_unlock(&s->mutex);return result;}\n'
    ref=source.replace('if('+predicate+')','while('+predicate+')')
    producer='#include "state.h"\nvoid complete(State*s){pthread_mutex_lock(&s->mutex);'+publish+'sched_yield();pthread_cond_broadcast(&s->changed);pthread_mutex_unlock(&s->mutex);}\n'
    desc=['A queue consumer must wait until one item is ready even after an empty broadcast, consume exactly one value 42 and clear readiness.', 'A result waiter must recheck its done predicate after every condition wakeup; preserve result 73 and consume completion exactly once.', 'A generation waiter must remain blocked until generation reaches two even after an intermediate wakeup; then observe value 88 and mark generation three.'][kind]+' The protected wait helper announces entry and records wakeups. Preserve both yields.'
    oracle='#include "state.h"\n#include <stdio.h>\nState s;int observed;void*w(void*x){observed=await_value(&s);return 0;}int main(int argc,char**argv){pthread_mutex_init(&s.mutex,0);pthread_cond_init(&s.changed,0);sem_init(&s.waiting,0,0);atomic_init(&s.awakened,0);'+init+'pthread_t t;pthread_create(&t,0,w,0);sem_wait(&s.waiting);pthread_mutex_lock(&s.mutex);pthread_cond_broadcast(&s.changed);pthread_mutex_unlock(&s.mutex);while(atomic_load(&s.awakened)<1)sched_yield();complete(&s);pthread_join(t,0);int ok=observed=='+str(value)+' && '+final+';'+MAIN_END
    return header,{'await.c':source,'complete.c':producer},{'await.c':ref,'complete.c':producer},oracle,desc,'semantic'


def nested(kind):
    fields=['int value;','int count,sum;','int committed,bytes;'][kind]
    work=['s->value++;','s->count++;s->sum+=6;','s->committed++;s->bytes+=13;'][kind]
    final=['s.value==160','s.count==160 && s.sum==960','s.committed==160 && s.bytes==2080'][kind]
    observe=['int v=s->value;','int v=s->count+s->sum;','int v=s->committed+s->bytes;'][kind]
    helper='static inline void audit(State*s){pthread_mutex_lock(&s->mutex);'+observe+'(void)v;atomic_fetch_add(&s->audits,1);pthread_mutex_unlock(&s->mutex);}'
    header=COMMON+'typedef struct {pthread_mutex_t mutex;atomic_int audits;'+fields+'} State;\n'+helper+'\nvoid commit(State*);int count_audits(State*);'+END
    source='#include "state.h"\nvoid commit(State*s){pthread_mutex_lock(&s->mutex);'+work+'sched_yield();audit(s);pthread_mutex_unlock(&s->mutex);}\n'
    ref=source.replace('audit(s);pthread_mutex_unlock(&s->mutex);','pthread_mutex_unlock(&s->mutex);audit(s);')
    other='#include "state.h"\nint count_audits(State*s){return atomic_load(&s->audits);}\n'
    desc=['Each of 160 updates increments value and invokes audit exactly once.', 'Each of 160 updates increments count and adds six to sum, then invokes audit exactly once.', 'Each of 160 commits records one commit and thirteen bytes, then invokes audit exactly once.'][kind]+' The protected audit helper acquires the shared mutex itself; avoid recursive acquisition while preserving synchronization, functional work and the yield.'
    oracle='#include "state.h"\n#include <stdio.h>\n#include <string.h>\nState s;void*w(void*x){for(int i=0;i<40;i++)commit(&s);return 0;}int main(int argc,char**argv){memset(&s,0,sizeof s);pthread_mutex_init(&s.mutex,0);atomic_init(&s.audits,0);pthread_t t[4];for(int i=0;i<4;i++)pthread_create(&t[i],0,w,0);for(int i=0;i<4;i++)pthread_join(t[i],0);int ok=count_audits(&s)==160 && '+final+';'+MAIN_END
    return header,{'commit.c':source,'read.c':other},{'commit.c':ref,'read.c':other},oracle,desc,'deadlock'


def aggregate(kind):
    fields=['int sum,count;','int total,accepted,rejected;','int parity[2],total;'][kind]
    work=['int n=s->count,t=s->sum;sched_yield();s->count=n+1;s->sum=t+5;', 'int n=s->total;int a=s->accepted,r=s->rejected;sched_yield();s->total=n+1;if(step%3==0)s->rejected=r+1;else s->accepted=a+1;', 'int n=s->parity[step&1],t=s->total;sched_yield();s->parity[step&1]=n+1;s->total=t+1;'][kind]
    read=['int n=s->count,t=s->sum;return t==n*5;', 'int t=s->total,a=s->accepted,r=s->rejected;return t==a+r;', 'int a=s->parity[0],b=s->parity[1],t=s->total;return a+b==t;'][kind]
    final=['s.count==320 && s.sum==1600','s.total==320 && s.accepted==212 && s.rejected==108','s.total==320 && s.parity[0]==160 && s.parity[1]==160'][kind]
    header=COMMON+'typedef struct {pthread_mutex_t mutex;'+fields+'} State;\nvoid record(State*,int);int consistent(State*);'+END
    source='#include "state.h"\nvoid record(State*s,int step){'+work+'}\n'
    other='#include "state.h"\nint consistent(State*s){'+read+'}\n'
    ref='#include "state.h"\nvoid record(State*s,int step){pthread_mutex_lock(&s->mutex);'+work+'pthread_mutex_unlock(&s->mutex);}\n'
    pre,ret=read.rsplit('return ',1)
    refother='#include "state.h"\nint consistent(State*s){pthread_mutex_lock(&s->mutex);'+pre+'int result='+ret+'pthread_mutex_unlock(&s->mutex);return result;}\n'
    desc=['Every record adds one count and five sum units; all concurrent readers must observe that invariant.', 'Every record increments total and exactly one of accepted or rejected according to step modulo three; preserve counts 320, 212 and 108 and consistent snapshots.', 'Each record increments one parity bucket and total as one transaction; both buckets must sum to total in every snapshot.'][kind]+' Preserve all updates and the yield.'
    corrupt=['s.sum++;','s.accepted++;','s.parity[0]++;'][kind]
    restore=['s.sum--;','s.accepted--;','s.parity[0]--;'][kind]
    oracle='#include "state.h"\n#include <stdio.h>\n#include <string.h>\nState s;atomic_int bad;void*w(void*x){for(int i=0;i<80;i++)record(&s,i);return 0;}void*r(void*x){for(int i=0;i<320;i++)if(!consistent(&s))atomic_store(&bad,1);return 0;}int main(int argc,char**argv){memset(&s,0,sizeof s);pthread_mutex_init(&s.mutex,0);int startup_ok=consistent(&s);'+corrupt+'startup_ok &= !consistent(&s);'+restore+'atomic_init(&bad,0);pthread_t t[5];for(int i=0;i<4;i++)pthread_create(&t[i],0,w,0);pthread_create(&t[4],0,r,0);for(int i=0;i<5;i++)pthread_join(t[i],0);int ok=startup_ok && !atomic_load(&bad) && '+final+';'+MAIN_END
    return header,{'record.c':source,'read.c':other},{'record.c':ref,'read.c':refother},oracle,desc,'race'


FAMILIES=[('ledger',counter),('snapshot',pair),('capacity',early),('rendezvous',barrier),('lock_order',order),('predicate',condition),('audit',nested),('aggregate',aggregate)]
# Splits are chosen by program design before calibration/training; each family has fresh control flow in held-out variant 2.
TRAIN={(0,0),(0,1),(1,0),(1,1),(2,0),(2,1),(3,0),(3,1),(4,0),(5,0),(6,0),(7,0)}
DEV={(4,1),(5,1),(6,1),(7,1)}


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reviewed_contract(task,description):
    contract={'schema_version':1,'project':task['task_id'],'description':description,'origin':'synthetic_example',
        'source_files':task['source_files'],'support_files':task['support_files'],'build_command':task['build_command'],
        'run_command':task['run_command'],'binary_path':'app','expected_behavior':'PASS',
        'max_runtime_seconds':2,'baseline_runs':3,'execution_backend':'nebius',
        'budgets':{'max_model_calls':3,'max_total_tokens':240000,'max_input_tokens_per_call':48000,
            'max_output_tokens_per_call':8192,'max_wall_seconds':1800},
        'verification':task['verification_config']}
    return RepositoryContract.model_validate(contract).model_dump(mode='json')


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    (OUT/'references').mkdir(); records=[]
    for family_index,(family,builder) in enumerate(FAMILIES):
        for variant in range(3):
            split='train' if (family_index,variant) in TRAIN else ('validation' if (family_index,variant) in DEV else 'test')
            name=f'{family}_{variant+1}'
            header,sources,references,oracle,description,negative=builder(variant)
            taskdir=OUT/'tasks'/name;taskdir.mkdir(parents=True)
            for filename,content in {**sources,'state.h':header,'oracle.c':oracle}.items():
                (taskdir/filename).write_text(content,encoding='utf-8',newline='')
            reference_dir=OUT/'references'/name;reference_dir.mkdir()
            for filename,content in references.items():(reference_dir/filename).write_text(content,encoding='utf-8',newline='')
            build=['gcc','-pthread','-g','-O1',*sources,'oracle.c','-o','app']
            requirement=description
            task={'task_id':name,'workspace':str(taskdir),'source_files':list(sources),'support_files':['state.h','oracle.c'],
                'build_command':build,'run_command':['./app'],'binary_path':'app','expected_behavior':'PASS','stress_runs':3,'max_runtime_seconds':2,
                'verification_config':{'required_build_success':True,'stress_runs':100,'required_original_tests':True,'original_test_commands':[['./app','--check']],
                    'sanitizer_enabled':True,'sanitizer_required':True,'sanitizer_runs':3,'sanitizer_compiler':'clang',
                    'semantic_checks':[{'name':requirement,'build_command':build,'run_command':['./app','--check'],'expected_stdout':'SEMANTIC_PASS','required':True}]},
                'metadata':{'fixture_description':description,'split':split,'family':family,'variant':variant+1}}
            (taskdir/'task.json').write_text(json.dumps(task,indent=2),encoding='utf-8')
            source_hashes={n:digest(taskdir/n) for n in sources};support_hashes={n:digest(taskdir/n) for n in task['support_files']}
            contract=reviewed_contract(task,description)
            (taskdir/'contract.json').write_text(json.dumps(contract,indent=2),encoding='utf-8')
            record={'id':name,'split':split,'family':family,'variant':variant+1,'task':f'tasks/{name}/task.json','negative_control':negative,
                'source_sha256':source_hashes,'support_sha256':support_hashes,'reference_sha256':{n:digest(reference_dir/n) for n in sources},
                'description':description,'runtime_context_files':['state.h'],'protected_oracle_files':['oracle.c']}
            records.append(record)
    manifest={'schema_version':2,'output_format':'tagged_source','base_model':'Qwen/Qwen2.5-Coder-1.5B-Instruct',
        'split_unit':'whole program design','train_programs':12,'validation_programs':4,'test_programs':8,
        'cases':records,'records':records,'test_source':str(OUT.relative_to(ROOT)).replace('\\','/'),
        'training_files':['train.jsonl','validation.jsonl'],'status':'frozen_pending_remote_calibration','test_targets_in_training':False,
        'limitations':['Synthetic pthreads programs, not real-repository accuracy evidence.','Synchronization families occur across splits; held-out implementations use different field invariants and control flow.','Targets require fresh remote calibration before training.'],
        'design_policy':'Splits frozen before first calibration. Any failed fixture remains immutable; corrected designs require a new version.'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Frozen:',OUT)
    print('12 train / 4 development / 8 held-out programs; no training JSONL emitted until references verify.')


def refresh_contracts():
    manifest=json.loads((OUT/'manifest.json').read_text());contracts={}
    for case in manifest['cases']:
        task=json.loads((OUT/case['task']).read_text())
        contract=reviewed_contract(task,case['description'])
        path=OUT/'tasks'/case['id']/'contract.json'
        path.write_text(json.dumps(contract,indent=2),encoding='utf-8')
        contracts[case['id']]=digest(path)
    policy={'schema_version':1,'frozen_manifest_sha256':digest(OUT/'manifest.json'),'contract_sha256':contracts,
        'origin':'Reviewed product route budget policy; task/source/support/reference hashes unchanged.',
        'max_model_calls':3,'max_output_tokens_per_call':8192,'max_total_tokens':240000}
    with (OUT/'budget-policy-v1.json').open('x',encoding='utf-8') as f:json.dump(policy,f,indent=2)
    print('Repository contracts normalized; frozen program manifests and oracles unchanged.')


def emit_training(calibration_path):
    manifest=json.loads((OUT/'manifest.json').read_text());calibration=json.loads(Path(calibration_path).read_text())
    verified={r['case']:r for r in calibration['cases'] if r.get('reference_verified') and r.get('broken_rejected')}
    training_out=ROOT/'datasets/adaptive-v3/training-v1'
    training_out.mkdir(parents=True,exist_ok=False)
    prior=ROOT/'datasets/adaptive-v2/pilot-v3'
    prior_manifest=json.loads((prior/'manifest.json').read_text())
    prior_records={r['id']:r for r in prior_manifest['records']}
    for filename,expected in prior_manifest['file_sha256'].items():
        if digest(prior/filename)!=expected:raise ValueError('Verified historical training data changed')
    emitted=[]
    for split in ('train','validation'):
        rows=[json.loads(line) for line in (prior/(split+'.jsonl')).read_text().splitlines()]
        emitted.extend({**prior_records[r['id']],'id':r['id'],'split':split,'origin':'datasets/adaptive-v2/pilot-v3','historical_verified':True} for r in rows)
        for item in manifest['cases']:
            if item['split']!=split:continue
            if item['id'] not in verified:raise ValueError('Cannot train on an unverified reference: '+item['id'])
            name=item['id'];task=ROOT/manifest['test_source']/'tasks'/name
            original={n:(task/n).read_text(encoding='utf-8') for n in item['source_sha256']}
            corrected={n:(OUT/'references'/name/n).read_text(encoding='utf-8') for n in original}
            for filename in original:
                if hashlib.sha256(original[filename].encode()).hexdigest()!=item['source_sha256'][filename]:raise ValueError('Original source changed')
                if hashlib.sha256(corrected[filename].encode()).hexdigest()!=item['reference_sha256'][filename]:raise ValueError('Reference changed')
                if original[filename].count('sched_yield(')!=corrected[filename].count('sched_yield('):raise ValueError('Reference changed scheduling hooks')
            prompt=tagged_messages(original,item['description'],{'state.h':(task/'state.h').read_text()},[item['description']])
            answer=''.join('<<<FILE:'+n+'>>>\n'+s+'<<<END_FILE>>>\n' for n,s in corrected.items())
            rows.append({'id':name,'messages':prompt+[{'role':'assistant','content':answer}]})
            emitted.append({**item,'calibration':str(Path(calibration_path).resolve().relative_to(ROOT))})
        path=training_out/(split+'.jsonl')
        with path.open('x',encoding='utf-8') as f:f.write(''.join(json.dumps(r)+'\n' for r in rows))
    receipt={'schema_version':2,'output_format':'tagged_source','base_model':'Qwen/Qwen2.5-Coder-1.5B-Instruct',
        'calibration':str(Path(calibration_path).resolve().relative_to(ROOT)),'product_manifest_sha256':digest(OUT/'manifest.json'),
        'historical_manifest_sha256':digest(prior/'manifest.json'),
        'train_programs':20,'validation_programs':5,'test_programs':8,'test_targets_in_training':False,
        'split_unit':'whole program design, frozen before calibration','test_source':str(OUT.relative_to(ROOT)).replace('\\','/'),
        'training_files':manifest['training_files'],'records':emitted,
        'file_sha256':{n:digest(training_out/n) for n in manifest['training_files']},
        'limitations':manifest['limitations']+['Eight earlier train programs and one earlier development program retained; earlier seen examples are not independent accuracy evidence.']}
    (training_out/'manifest.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    (OUT/'training-ready.json').write_text(json.dumps({'training_dataset':str(training_out.relative_to(ROOT)),'manifest_sha256':digest(training_out/'manifest.json')},indent=2),encoding='utf-8')
    print('Verified training rows emitted:',training_out)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--emit-training',type=Path);p.add_argument('--refresh-contracts',action='store_true');p.add_argument('--data',type=Path);args=p.parse_args()
    if args.data:OUT=args.data.resolve()
    if args.emit_training:emit_training(args.emit_training)
    elif args.refresh_contracts:refresh_contracts()
    else:main()
