FROM alpine:3.20
ARG FIXTURE_REVISION=local
LABEL org.opencontainers.image.revision="${FIXTURE_REVISION}"
RUN apk add --no-cache dovecot \
 && adduser -D -u 5000 vmail
COPY 10-mail.conf 10-auth.conf 10-master.conf /etc/dovecot/conf.d/
COPY users /etc/dovecot/users
RUN printf 'protocols = imap\n!include conf.d/*.conf\nssl = no\nlog_path = /dev/stderr\nnamespace inbox {\n  inbox = yes\n  separator = /\n}\n' > /etc/dovecot/dovecot.conf \
 && mkdir -p /var/mail/alice@kkmail.test/Maildir/{new,cur,tmp} \
 && chown -R vmail:vmail /var/mail
COPY seed.eml /var/mail/alice@kkmail.test/Maildir/new/1000.kkmail.local
RUN chown -R vmail:vmail /var/mail
EXPOSE 143
CMD ["dovecot", "-F"]
