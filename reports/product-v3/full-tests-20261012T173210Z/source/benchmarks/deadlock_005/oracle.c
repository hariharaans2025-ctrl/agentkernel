#include <pthread.h>
#include <stdatomic.h>
#define main fixture_main
#include "main.c"
#undef main
int main(void) { if(fixture_main()!=0) return 1; if(!(shutdown_requested==1 && pending==0 && completed==3)) { puts("SEMANTIC_FAIL"); return 2; } puts("SEMANTIC_PASS"); return 0; }
