#include "queue.h"
#include <string.h>
#include <stdio.h>

void queue_init(JobQueue *q, int count) {
    memset(q, 0, sizeof(*q));
    pthread_mutex_init(&q->queue_lock, 0);
    pthread_mutex_init(&q->stats_lock, 0);
    pthread_barrier_init(&q->reproduce_barrier, 0, 2);
    q->length = count;
    for (int i = 0; i < count; ++i) q->jobs[i] = i + 1;
}

int queue_process_one(JobQueue *q, int force_overlap) {
    pthread_mutex_lock(&q->queue_lock);
    /* Test scheduling hook: overlap the two operations while holding first locks. */
    if (force_overlap) pthread_barrier_wait(&q->reproduce_barrier);
    if (force_overlap) fprintf(stderr, "WORKER HOLD queue WAIT stats\n");
    pthread_mutex_lock(&q->stats_lock);
    int available = q->next < q->length;
    if (available) {
        int index = q->next++;
        q->checksum += q->jobs[index];
        q->seen[index]++;
        q->completed++;
    }
    pthread_mutex_unlock(&q->stats_lock);
    pthread_mutex_unlock(&q->queue_lock);
    return available;
}

int queue_inspect(JobQueue *q, int force_overlap) {
    /* Intentional fault: monitoring acquires the same locks in reverse order. */
    pthread_mutex_lock(&q->stats_lock);
    if (force_overlap) pthread_barrier_wait(&q->reproduce_barrier);
    if (force_overlap) fprintf(stderr, "MONITOR HOLD stats WAIT queue\n");
    pthread_mutex_lock(&q->queue_lock);
    int outstanding = q->length - q->completed;
    pthread_mutex_unlock(&q->queue_lock);
    pthread_mutex_unlock(&q->stats_lock);
    return outstanding;
}

void queue_destroy(JobQueue *q) {
    pthread_barrier_destroy(&q->reproduce_barrier);
    pthread_mutex_destroy(&q->stats_lock);
    pthread_mutex_destroy(&q->queue_lock);
}
