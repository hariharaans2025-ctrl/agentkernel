#include <pthread.h>
#include <stdatomic.h>
#define main fixture_main
#include "main.c"
#undef main
int main(void) { if(fixture_main()!=0) return 1; if(!(reads>0 && bad_reads==0 && config.version==10000 && config.inverse==~10000)) { puts("SEMANTIC_FAIL"); return 2; } puts("SEMANTIC_PASS"); return 0; }
