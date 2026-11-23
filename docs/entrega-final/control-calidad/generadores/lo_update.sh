#!/bin/bash
# uso: lo_update.sh in.docx out.docx out.pdf  (actualiza índices/campos con LibreOffice y exporta)
S=/private/tmp/claude-501/-Users-yeseniaramirezmedina-Workspace-NexoEventos/c876ff31-649b-4863-a3a9-dcfdc5f3fffd/scratchpad
IN=$(cd "$(dirname "$1")"; pwd)/$(basename "$1"); OD=$(cd "$(dirname "$2")"; pwd)/$(basename "$2"); OP=$(cd "$(dirname "$3")"; pwd)/$(basename "$3")
cat > $S/loprof/user/basic/Standard/Module1.xba <<XBA
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
Sub Upd
  Dim a(0) As New com.sun.star.beans.PropertyValue
  a(0).Name = &quot;Hidden&quot; : a(0).Value = True
  oDoc = StarDesktop.loadComponentFromURL(ConvertToURL(&quot;$IN&quot;), &quot;_blank&quot;, 0, a())
  For k = 1 To 2
    oIdx = oDoc.getDocumentIndexes()
    For i = 0 To oIdx.getCount() - 1
      oIdx.getByIndex(i).update()
    Next i
    oDoc.getTextFields().refresh()
    oDoc.refresh()
  Next k
  Dim b(0) As New com.sun.star.beans.PropertyValue
  b(0).Name = &quot;FilterName&quot; : b(0).Value = &quot;MS Word 2007 XML&quot;
  oDoc.storeToURL(ConvertToURL(&quot;$OD&quot;), b())
  Dim c(0) As New com.sun.star.beans.PropertyValue
  c(0).Name = &quot;FilterName&quot; : c(0).Value = &quot;writer_pdf_Export&quot;
  oDoc.storeToURL(ConvertToURL(&quot;$OP&quot;), c())
  oDoc.close(True)
  StarDesktop.terminate()
End Sub
</script:module>
XBA
/Applications/LibreOffice.app/Contents/MacOS/soffice --headless --norestore -env:UserInstallation=file://$S/loprof "vnd.sun.star.script:Standard.Module1.Upd?language=Basic&location=application" 2>&1 | grep -v Fontconfig
