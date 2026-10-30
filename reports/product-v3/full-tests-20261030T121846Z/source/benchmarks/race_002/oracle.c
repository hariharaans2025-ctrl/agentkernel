#include <pthread.h>
#include <stdatomic.h>
#define main fixture_main
#include "main.c"
#undef main
int main(void) { if(fixture_main()!=0) return 1; if(!(balance==1000 && completed[0]==10000 && completed[1]==10000)) { puts("SEMANTIC_FAIL"); return 2; } puts("SEMANTIC_PASS"); return 0; }
