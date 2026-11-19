# Any Dockerfile works: aember-pack builds it for the aember target's
# platform and exports the file system. (A RUN step for another
# architecture needs binfmt/qemu-user on the build machine.)
FROM alpine:3.20
COPY hello.sh /usr/local/bin/hello
RUN chmod 0755 /usr/local/bin/hello
CMD ["/usr/local/bin/hello"]
