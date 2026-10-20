FROM alpine:3.20
RUN apk add --no-cache dovecot \
 && adduser -D -u 5000 vmail
COPY 10-mail.conf 10-auth.conf 10-master.conf /etc/dovecot/conf.d/
COPY users /etc/dovecot/users
RUN printf 'ssl = no\nprotocols = imap\n!include conf.d/*.conf\n' > /etc/dovecot/dovecot.conf \
 && mkdir -p /var/mail/alice@kkmail.test/Maildir/{new,cur,tmp} \
 && chown -R vmail:vmail /var/mail
COPY seed.eml /var/mail/alice@kkmail.test/Maildir/new/1000.kkmail.local
RUN chown -R vmail:vmail /var/mail
EXPOSE 143
CMD ["dovecot", "-F"]
