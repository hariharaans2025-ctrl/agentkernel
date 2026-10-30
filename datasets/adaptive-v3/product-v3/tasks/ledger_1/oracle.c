#include "state.h"
#include <stdio.h>
State s; atomic_int bad;
void* worker(void*x){for(int i=0;i<80;i++) update(&s,i);return 0;}
void* monitor(void*x){for(int i=0;i<320;i++){long v=snapshot(&s);if(!(v>=0 && v<=960))atomic_store(&bad,1);}return 0;}
int main(int argc,char**argv){pthread_mutex_init(&s.mutex,0); s.credits=0;s.credits=13;int startup_ok=snapshot(&s)==13;s.credits=0; atomic_init(&bad,0); pthread_t t[5];for(int i=0;i<4;i++)pthread_create(&t[i],0,worker,0);pthread_create(&t[4],0,monitor,0);for(int i=0;i<5;i++)pthread_join(t[i],0);int ok=startup_ok && (s.credits==960) && (snapshot(&s)==960) && !atomic_load(&bad);if(!ok) { puts("FAIL"); return 1; } puts(argc>1?"SEMANTIC_PASS":"PASS"); return 0;}
