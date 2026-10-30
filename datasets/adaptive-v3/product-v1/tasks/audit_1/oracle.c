#include "state.h"
#include <stdio.h>
#include <string.h>
State s;void*w(void*x){for(int i=0;i<40;i++)commit(&s);return 0;}int main(int argc,char**argv){memset(&s,0,sizeof s);pthread_mutex_init(&s.mutex,0);atomic_init(&s.audits,0);pthread_t t[4];for(int i=0;i<4;i++)pthread_create(&t[i],0,w,0);for(int i=0;i<4;i++)pthread_join(t[i],0);int ok=count_audits(&s)==160 && s.value==160;if(!ok) { puts("FAIL"); return 1; } puts(argc>1?"SEMANTIC_PASS":"PASS"); return 0;}
