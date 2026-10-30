#ifndef STATE_H
#define STATE_H
#include <pthread.h>
typedef struct { pthread_mutex_t mutex; int remaining; } Inventory;
int take_item(Inventory *);
int remaining_stock(Inventory *);
#endif
