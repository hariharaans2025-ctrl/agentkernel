#include <pthread.h>
#include <stdatomic.h>
#define main fixture_main
#include "main.c"
#undef main
int main(void) { if(fixture_main()!=0) return 1; if(!(tail==200 && consumed==200)) { puts("SEMANTIC_FAIL"); return 2; } for(int i=0;i<200;i++) if(seen[i]!=1) return 3; puts("SEMANTIC_PASS"); return 0; }
