#include "state.h"
#include <stdio.h>
State s;atomic_int bad;
void*w(void*x){for(int k=1;k<=60;k++)publish(&s,k);return 0;}
void*r(void*x){for(int k=0;k<180;k++)if(!check_snapshot(&s))atomic_store(&bad,1);return 0;}
int main(int argc,char**argv){pthread_mutex_init(&s.mutex,0);s.tag=0;s.checksum=0x65;atomic_init(&bad,0);pthread_t t[3];pthread_create(&t[0],0,w,0);pthread_create(&t[1],0,r,0);pthread_create(&t[2],0,r,0);for(int i=0;i<3;i++)pthread_join(t[i],0);int ok=!atomic_load(&bad) && (s.tag==60 && s.checksum==(60^0x65));if(!ok) { puts("FAIL"); return 1; } puts(argc>1?"SEMANTIC_PASS":"PASS"); return 0;}
