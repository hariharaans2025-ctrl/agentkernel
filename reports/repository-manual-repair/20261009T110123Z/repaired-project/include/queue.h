#ifndef JOB_QUEUE_H
#define JOB_QUEUE_H
#include <pthread.h>
#define JOB_CAPACITY 128
typedef struct {
    pthread_mutex_t queue_lock;
    pthread_mutex_t stats_lock;
    pthread_barrier_t reproduce_barrier;
    int jobs[JOB_CAPACITY];
    int next;
    int length;
    int completed;
    long checksum;
    int seen[JOB_CAPACITY];
} JobQueue;
void queue_init(JobQueue *queue, int count);
int queue_process_one(JobQueue *queue, int force_overlap);
int queue_inspect(JobQueue *queue, int force_overlap);
void queue_destroy(JobQueue *queue);
#endif
