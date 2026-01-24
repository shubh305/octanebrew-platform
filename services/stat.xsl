<?xml version="1.0" encoding="utf-8" ?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">

<xsl:template match="/">
    <html>
        <head>
            <title>RTMP Statistics // OctaneBrew</title>
            <link rel="stylesheet" href="/style.css"/>
        </head>
        <body class="stats-page">
            <header>
                <h1>OpenStream // Signal Status</h1>
                <div class="subtitle">INGEST NODE DIAGNOSTICS</div>
            </header>

            <div class="container">
                <div class="dashboard server-metrics">
                    <div class="card">
                        <span class="card-title">System</span>
                        <span class="card-desc">
                            Nginx: <xsl:value-of select="/rtmp/nginx_version"/><br/>
                            Module: <xsl:value-of select="/rtmp/nginx_rtmp_version"/><br/>
                            PID: <xsl:value-of select="/rtmp/pid"/>
                        </span>
                    </div>
                    <div class="card">
                        <span class="card-title">Uptime</span>
                        <span class="card-desc">
                            <xsl:call-template name="showtime">
                                <xsl:with-param name="time" select="/rtmp/uptime * 1000"/>
                            </xsl:call-template>
                        </span>
                    </div>
                    <div class="card">
                        <span class="card-title">Connections</span>
                        <span class="card-desc">
                            Accepted: <xsl:value-of select="/rtmp/naccepted"/>
                        </span>
                    </div>
                    <div class="card">
                        <span class="card-title">Bandwidth</span>
                        <span class="card-desc">
                            In: <xsl:call-template name="showsize"><xsl:with-param name="size" select="/rtmp/bw_in"/><xsl:with-param name="bits" select="1"/><xsl:with-param name="persec" select="1"/></xsl:call-template><br/>
                            Out: <xsl:call-template name="showsize"><xsl:with-param name="size" select="/rtmp/bw_out"/><xsl:with-param name="bits" select="1"/><xsl:with-param name="persec" select="1"/></xsl:call-template>
                        </span>
                    </div>
                </div>

                <xsl:apply-templates select="rtmp"/>
            </div>

            <div class="footer">
                Built <xsl:value-of select="/rtmp/built"/>
            </div>
        </body>
    </html>
</xsl:template>

<xsl:template match="rtmp">
    <table class="stats-table">
        <thead>
            <tr>
                <th>Stream</th>
                <th>Clients</th>
                <th>Video</th>
                <th>Res</th>
                <th>FPS</th>
                <th>Audio</th>
                <th>Freq</th>
                <th>Chan</th>
                <th>In</th>
                <th>Out</th>
                <th>BW In</th>
                <th>BW Out</th>
                <th>State</th>
                <th>Time</th>
            </tr>
        </thead>
        <tbody>
            <xsl:apply-templates select="server"/>
        </tbody>
    </table>
</xsl:template>

<xsl:template match="server">
    <xsl:apply-templates select="application"/>
</xsl:template>

<xsl:template match="application">
    <tr>
        <td colspan="14" class="section-header">
            <b>APP: <xsl:value-of select="name"/></b>
        </td>
    </tr>
    <xsl:apply-templates select="live"/>
    <xsl:apply-templates select="play"/>
</xsl:template>

<xsl:template match="live">
    <xsl:apply-templates select="stream"/>
</xsl:template>

<xsl:template match="play">
    <xsl:apply-templates select="stream"/>
</xsl:template> 

<xsl:template match="stream">
    <tr valign="top">
        <xsl:attribute name="class">
            <xsl:choose>
                <xsl:when test="active">active</xsl:when>
                <xsl:otherwise>idle</xsl:otherwise>
            </xsl:choose>
        </xsl:attribute>
        <td>
            <a href="">
                <xsl:attribute name="onclick">
                    var d=document.getElementById('<xsl:value-of select="../../name"/>-<xsl:value-of select="name"/>');
                    d.style.display=d.style.display=='none'?'':'none';
                    return false
                </xsl:attribute>
                <xsl:value-of select="name"/>
                <xsl:if test="string-length(name) = 0">[EMPTY]</xsl:if>
            </a>
        </td>
        <td align="middle"> <xsl:value-of select="nclients"/> </td>
        
        <td>
            <xsl:value-of select="meta/video/codec"/>&#160;<xsl:value-of select="meta/video/profile"/>
        </td>
        <td><xsl:apply-templates select="meta/video/width"/></td>
        <td><xsl:value-of select="meta/video/frame_rate"/></td>

        <td><xsl:value-of select="meta/audio/codec"/></td>
        <td><xsl:apply-templates select="meta/audio/sample_rate"/></td>
        <td><xsl:value-of select="meta/audio/channels"/></td>
        <td><xsl:call-template name="showsize"><xsl:with-param name="size" select="bytes_in"/></xsl:call-template></td>
        <td><xsl:call-template name="showsize"><xsl:with-param name="size" select="bytes_out"/></xsl:call-template></td>
        <td><xsl:call-template name="showsize"><xsl:with-param name="size" select="bw_in"/><xsl:with-param name="bits" select="1"/><xsl:with-param name="persec" select="1"/></xsl:call-template></td>
        <td><xsl:call-template name="showsize"><xsl:with-param name="size" select="bw_out"/><xsl:with-param name="bits" select="1"/><xsl:with-param name="persec" select="1"/></xsl:call-template></td>
        
        <td><xsl:call-template name="streamstate"/></td>
        <td><xsl:call-template name="showtime"><xsl:with-param name="time" select="time"/></xsl:call-template></td>
    </tr>
    
    <tr style="display:none">
        <xsl:attribute name="id">
            <xsl:value-of select="../../name"/>-<xsl:value-of select="name"/>
        </xsl:attribute>
        <td colspan="14" style="padding: 0; border: none;">
            <table class="stats-table" style="background: #111; margin: 0; width: 100%; border-left: none; border-right: none;">
                <tr>
                    <th>Id</th>
                    <th>State</th>
                    <th>IP Address</th>
                    <th>Flash Version</th>
                    <th>Dropped</th>
                    <th>A-V Sync</th>
                    <th>Time</th>
                </tr>
                <xsl:apply-templates select="client"/>
            </table>
        </td>
    </tr>
</xsl:template>

<xsl:template match="client">
    <tr>
        <xsl:attribute name="class">
            <xsl:choose>
                <xsl:when test="publishing">publishing</xsl:when>
                <xsl:otherwise>playing</xsl:otherwise>
            </xsl:choose>
        </xsl:attribute>
        <td><xsl:value-of select="id"/></td>
        <td><xsl:call-template name="clientstate"/></td>
        <td>
            <a target="_blank">
                <xsl:attribute name="href">https://apps.db.ripe.net/db-web-ui/query?searchtext=<xsl:value-of select="address"/></xsl:attribute>
                <xsl:value-of select="address"/>
            </a>
        </td>
        <td><xsl:value-of select="flashver"/></td>
        <td><xsl:value-of select="dropped"/></td>
        <td><xsl:value-of select="avsync"/></td>
        <td><xsl:call-template name="showtime"><xsl:with-param name="time" select="time"/></xsl:call-template></td>
    </tr>
</xsl:template>

<xsl:template name="showtime">
    <xsl:param name="time"/>
    <xsl:if test="$time &gt; 0">
        <xsl:variable name="sec"><xsl:value-of select="floor($time div 1000)"/></xsl:variable>
        <xsl:if test="$sec &gt;= 86400"><xsl:value-of select="floor($sec div 86400)"/>d </xsl:if>
        <xsl:if test="$sec &gt;= 3600"><xsl:value-of select="(floor($sec div 3600)) mod 24"/>h </xsl:if>
        <xsl:if test="$sec &gt;= 60"><xsl:value-of select="(floor($sec div 60)) mod 60"/>m </xsl:if>
        <xsl:value-of select="$sec mod 60"/>s
    </xsl:if>
</xsl:template>

<xsl:template name="showsize">
    <xsl:param name="size"/>
    <xsl:param name="bits" select="0" />
    <xsl:param name="persec" select="0" />
    <xsl:variable name="sizen"><xsl:value-of select="floor($size div 1024)"/></xsl:variable>
    <xsl:choose>
        <xsl:when test="$sizen &gt;= 1073741824"><xsl:value-of select="format-number($sizen div 1073741824,'#.###')"/> T</xsl:when>
        <xsl:when test="$sizen &gt;= 1048576"><xsl:value-of select="format-number($sizen div 1048576,'#.###')"/> G</xsl:when>
        <xsl:when test="$sizen &gt;= 1024"><xsl:value-of select="format-number($sizen div 1024,'#.##')"/> M</xsl:when>
        <xsl:when test="$sizen &gt;= 0"><xsl:value-of select="$sizen"/> K</xsl:when>
    </xsl:choose>
    <xsl:if test="string-length($size) &gt; 0">
        <xsl:choose>
            <xsl:when test="$bits = 1">b</xsl:when>
            <xsl:otherwise>B</xsl:otherwise>
        </xsl:choose>
        <xsl:if test="$persec = 1">/s</xsl:if>
    </xsl:if>
</xsl:template>

<xsl:template name="streamstate">
    <xsl:choose>
        <xsl:when test="active"><span class="state-playing">ACTIVE</span></xsl:when>
        <xsl:otherwise>IDLE</xsl:otherwise>
    </xsl:choose>
</xsl:template>

<xsl:template name="clientstate">
    <xsl:choose>
        <xsl:when test="publishing"><span class="state-publishing">PUBLISHING</span></xsl:when>
        <xsl:otherwise>PLAYING</xsl:otherwise>
    </xsl:choose>
</xsl:template>

<xsl:template match="width">
    <xsl:value-of select="."/>x<xsl:value-of select="../height"/>
</xsl:template>

</xsl:stylesheet>