#include "state.h"
#include <stdio.h>
State s;atomic_int bad;void*w(void*x){for(int i=0;i<70;i++){if(acquire(&s)!=0)atomic_store(&bad,1);if(inspect(&s)!=10)atomic_store(&bad,1);}return 0;}
int main(int argc,char**argv){pthread_mutex_init(&s.mutex,0);s.available=10;s.claimed=0;atomic_init(&bad,0);int ok=1;for(int i=0;i<10;i++)ok &= acquire(&s)==1;pthread_t t[4];for(int i=0;i<4;i++)pthread_create(&t[i],0,w,0);for(int i=0;i<4;i++)pthread_join(t[i],0);ok &= !atomic_load(&bad) && (s.available==0 && s.claimed==10);if(!ok) { puts("FAIL"); return 1; } puts(argc>1?"SEMANTIC_PASS":"PASS"); return 0;}
