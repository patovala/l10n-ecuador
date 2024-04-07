BEGIN { FS="," }
NR==1 {
    for (i=1; i<=NF; i++) {
        tags[i] = $i
    }
    next
}
{
    if ($1 == "id")
        print "<record id=\"$1\">"
    else
        print "<record>"
    for (i=1; i<=NF; i++) {
        printf "    <%s>%s</%s>\n", tags[i], $i, tags[i]
    }
    print "</record>"
}
