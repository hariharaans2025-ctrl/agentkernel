#include "state.h"
#include <stdio.h>
#include <string.h>
State s;atomic_int bad;void*w(void*x){for(int i=0;i<80;i++)record(&s,i);return 0;}void*r(void*x){for(int i=0;i<320;i++)if(!consistent(&s))atomic_store(&bad,1);return 0;}int main(int argc,char**argv){memset(&s,0,sizeof s);pthread_mutex_init(&s.mutex,0);int startup_ok=consistent(&s);s.parity[0]++;startup_ok &= !consistent(&s);s.parity[0]--;atomic_init(&bad,0);pthread_t t[5];for(int i=0;i<4;i++)pthread_create(&t[i],0,w,0);pthread_create(&t[4],0,r,0);for(int i=0;i<5;i++)pthread_join(t[i],0);int ok=startup_ok && !atomic_load(&bad) && s.total==320 && s.parity[0]==160 && s.parity[1]==160;if(!ok) { puts("FAIL"); return 1; } puts(argc>1?"SEMANTIC_PASS":"PASS"); return 0;}
