#include <pthread.h>
#include <stdatomic.h>
#define main fixture_main
#include "main.c"
#undef main
int main(void) { if(fixture_main()!=0) return 1; if(!(cache_value==42 && logged_value==42 && reads==2 && logs==2)) { puts("SEMANTIC_FAIL"); return 2; } puts("SEMANTIC_PASS"); return 0; }
