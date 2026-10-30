#ifndef STATE_H
#define STATE_H
#include <pthread.h>
typedef struct { pthread_mutex_t mutex; int next_ticket; } TicketOffice;
int reserve_ticket(TicketOffice *);
int issued_count(TicketOffice *);
#endif
