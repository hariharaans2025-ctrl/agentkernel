CC = gcc
CFLAGS = -pthread -g -O1 -Iinclude

job_service: src/main.c src/queue.c include/queue.h
	$(CC) $(CFLAGS) src/main.c src/queue.c -o job_service

test: job_service
	./job_service --smoke
	./job_service --check
