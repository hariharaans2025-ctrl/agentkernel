/* Synthetic two-account transfer inversion; preserve both transfers and totals. */
#include <pthread.h>
#include <stdio.h>
static pthread_mutex_t account_a = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t account_b = PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t start;
static int balance_a = 100, balance_b = 100, transfers;
static void *transfer(void *arg) {
    int reverse = *(int *)arg;
#ifdef REPAIRED
    pthread_barrier_wait(&start);
    pthread_mutex_lock(&account_a);
    pthread_mutex_lock(&account_b);
#else
    pthread_mutex_lock(reverse ? &account_b : &account_a);
    pthread_barrier_wait(&start);
    fprintf(stderr, "%s\n", reverse ? "RIGHT HOLD account_b WAIT account_a" : "LEFT HOLD account_a WAIT account_b");
    pthread_mutex_lock(reverse ? &account_a : &account_b);
#endif
    balance_a += reverse ? 10 : -10;
    balance_b += reverse ? -10 : 10;
    transfers++;
#ifdef REPAIRED
    pthread_mutex_unlock(&account_b);
    pthread_mutex_unlock(&account_a);
#else
    pthread_mutex_unlock(reverse ? &account_a : &account_b);
    pthread_mutex_unlock(reverse ? &account_b : &account_a);
#endif
    return 0;
}
int main(void) {
    pthread_t a, b;
    int forward = 0, reverse = 1;
    if (pthread_barrier_init(&start, 0, 2)) return 2;
    if (pthread_create(&a, 0, transfer, &forward) || pthread_create(&b, 0, transfer, &reverse)) return 2;
    if (pthread_join(a, 0) || pthread_join(b, 0)) return 2;
    pthread_barrier_destroy(&start);
    if (transfers != 2 || balance_a != 100 || balance_b != 100) { puts("SEMANTIC_FAIL"); return 1; }
    puts("SEMANTIC_PASS"); puts("PASS");
    return 0;
}
