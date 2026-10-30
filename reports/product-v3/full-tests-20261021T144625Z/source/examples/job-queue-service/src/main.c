/* Protected workload and semantic checks. Repair proposals may edit queue.c only. */
#include "queue.h"
#include <stdio.h>
#include <string.h>

typedef struct { JobQueue *queue; int reproduce; } Work;

static void *worker(void *opaque) {
    Work *work = opaque;
    int first = 1;
    while (queue_process_one(work->queue, first && work->reproduce)) first = 0;
    return 0;
}

static void *monitor(void *opaque) {
    Work *work = opaque;
    queue_inspect(work->queue, work->reproduce);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "--stress") && strcmp(argv[1], "--check") && strcmp(argv[1], "--smoke"))) return 2;
    int reproduce = !strcmp(argv[1], "--stress");
    int count = !strcmp(argv[1], "--smoke") ? 1 : 100;
    JobQueue queue;
    queue_init(&queue, count);
    Work work = {&queue, reproduce};
    pthread_t processor, observer;
    if (pthread_create(&processor, 0, worker, &work)) return 3;
    if (reproduce && pthread_create(&observer, 0, monitor, &work)) return 3;
    pthread_join(processor, 0);
    if (reproduce) pthread_join(observer, 0);
    else queue_inspect(&queue, 0);
    int correct = queue.completed == count && queue.next == count && queue.checksum == (long)count*(count+1)/2;
    for (int i = 0; i < count; ++i) correct = correct && queue.seen[i] == 1;
    printf("completed=%d checksum=%ld exactly_once=%s\n", queue.completed, queue.checksum, correct ? "yes" : "no");
    queue_destroy(&queue);
    if (!correct) { puts("SEMANTIC_FAIL"); return 1; }
    puts(reproduce ? "PASS" : "SEMANTIC_PASS");
    return 0;
}
