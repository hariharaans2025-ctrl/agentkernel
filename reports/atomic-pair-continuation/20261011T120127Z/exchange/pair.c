#include "pair.h"

void set_pair(int32_t a, int32_t b) {
    uint64_t packed = ((uint64_t)(uint32_t)a) | ((uint64_t)(uint32_t)b) << 32;
    atomic_exchange_explicit(&pair_bits, packed, memory_order_acq_rel);
}

void get_pair(int32_t *a, int32_t *b) {
    uint64_t packed = atomic_load_explicit(&pair_bits, memory_order_acquire);
    *a = (int32_t)(uint32_t)packed;
    *b = (int32_t)(uint32_t)(packed >> 32);
}
