#ifndef STATE_H
#define STATE_H
#include <pthread.h>
typedef struct { pthread_mutex_t mutex; long balance; } Account;
void deposit(Account *, int);
long read_balance(Account *);
#endif
