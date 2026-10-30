#include <stdint.h>
#include <stdatomic.h>
extern _Atomic(uint64_t) pair_bits;
void set_pair(int32_t a, int32_t b);
void get_pair(int32_t *a, int32_t *b);
